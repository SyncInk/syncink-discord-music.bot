import asyncio
import json
import aiohttp.web
from typing import Set, Dict, Optional, Any
from utils.logger import log
from services.music_service import MusicService

class DashboardWebSocketManager:
    _instance: Optional['DashboardWebSocketManager'] = None

    def __init__(self):
        self._active_sockets: Set[aiohttp.web.WebSocketResponse] = set()
        self._socket_guild_subscriptions: Dict[aiohttp.web.WebSocketResponse, Optional[int]] = {}

    @classmethod
    def get_instance(cls) -> 'DashboardWebSocketManager':
        if cls._instance is None:
            cls._instance = DashboardWebSocketManager()
        return cls._instance

    async def handle_ws(self, request: aiohttp.web.Request) -> aiohttp.web.WebSocketResponse:
        ws = aiohttp.web.WebSocketResponse(heartbeat=25.0)
        await ws.prepare(request)

        self._active_sockets.add(ws)
        self._socket_guild_subscriptions[ws] = None
        log.debug(f"[Dashboard WS] Client connected. Total clients: {len(self._active_sockets)}")

        bot = request.app.get("bot")

        try:
            # Send initial system welcome
            await ws.send_json({
                "event": "connected",
                "message": "Connected to SyncInk Radio Live Gateway",
                "version": "2.5.0",
                "server_time": asyncio.get_event_loop().time()
            })

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        msg_type = data.get("type") or data.get("event")

                        if msg_type == "subscribe":
                            guild_id = data.get("guild_id")
                            if guild_id:
                                try:
                                    g_id = int(guild_id)
                                    self._socket_guild_subscriptions[ws] = g_id
                                    await self.send_guild_snapshot(ws, g_id, bot)
                                except (ValueError, TypeError):
                                    pass

                        elif msg_type == "ping":
                            await ws.send_json({"event": "pong", "time": asyncio.get_event_loop().time()})

                    except json.JSONDecodeError:
                        pass
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    log.debug(f"[Dashboard WS] Socket error: {ws.exception()}")
        finally:
            self._active_sockets.discard(ws)
            self._socket_guild_subscriptions.pop(ws, None)
            log.debug(f"[Dashboard WS] Client disconnected. Total clients: {len(self._active_sockets)}")

        return ws

    def serialize_guild_playback(self, guild_id: int, bot: Any) -> Dict[str, Any]:
        """Serializes current guild playback state for web clients."""
        service = MusicService.get_instance()
        queue = service.get_queue(guild_id)
        current = queue.current_track

        vc = None
        if bot:
            guild = bot.get_guild(guild_id)
            vc = (guild.voice_client if guild else None) or queue.voice_client
        else:
            vc = queue.voice_client

        is_connected = bool(vc and vc.is_connected())
        is_playing = bool(is_connected and vc and vc.is_playing())
        is_paused = bool(is_connected and vc and vc.is_paused())

        current_data = None
        if current:
            current_data = {
                "title": current.clean_title,
                "author": current.author or "Unknown Artist",
                "url": current.url,
                "thumbnail": current.thumbnail,
                "duration": current.duration,
                "formatted_duration": current.formatted_duration,
                "platform": current.platform,
                "is_radio": current.is_radio,
                "is_live": current.is_live,
                "requested_by": str(current.requested_by) if current.requested_by else None,
            }

        position = queue.get_playback_time() if is_playing or is_paused else 0.0

        upcoming = []
        for t in queue.tracks[:25]:
            upcoming.append({
                "title": t.clean_title,
                "author": t.author,
                "url": t.url,
                "thumbnail": t.thumbnail,
                "formatted_duration": t.formatted_duration,
                "platform": t.platform,
                "is_radio": t.is_radio
            })

        radio_name = None
        if queue.active_radio_station_info:
            radio_name = queue.active_radio_station_info.get("name")
        elif queue.active_radio_station:
            radio_name = queue.active_radio_station

        listeners_count = 0
        if vc and vc.channel:
            listeners_count = len([m for m in vc.channel.members if not m.bot])

        return {
            "guild_id": str(guild_id),
            "connected": is_connected,
            "channel_name": vc.channel.name if vc and vc.channel else None,
            "listeners": listeners_count,
            "is_playing": is_playing,
            "is_paused": is_paused,
            "current_track": current_data,
            "position": round(position, 1),
            "duration": current.duration if current else 0,
            "volume": queue.volume,
            "repeat_mode": queue.repeat_mode,
            "autoplay": queue.autoplay,
            "is_247": queue.is_247,
            "radio_station": radio_name,
            "queue": upcoming,
            "queue_size": len(queue.tracks),
        }

    async def send_guild_snapshot(self, ws: aiohttp.web.WebSocketResponse, guild_id: int, bot: Any):
        state = self.serialize_guild_playback(guild_id, bot)
        try:
            await ws.send_json({
                "event": "playback_update",
                "guild_id": str(guild_id),
                "data": state
            })
        except Exception:
            pass

    async def broadcast_playback_update(self, guild_id: int, bot: Any):
        """Broadcasts playback state updates to all subscribed web clients."""
        if not self._active_sockets:
            return

        state = self.serialize_guild_playback(guild_id, bot)
        payload = json.dumps({
            "event": "playback_update",
            "guild_id": str(guild_id),
            "data": state
        })

        tasks = []
        for ws in list(self._active_sockets):
            sub_id = self._socket_guild_subscriptions.get(ws)
            if sub_id is None or sub_id == guild_id:
                tasks.append(ws.send_str(payload))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
