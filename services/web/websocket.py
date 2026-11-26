import asyncio
import json
import time
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
                "server_time": time.time()
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
                                    if str(g_id).startswith("110000"):
                                        self._socket_guild_subscriptions[ws] = g_id
                                        await self.send_guild_snapshot(ws, g_id, bot)
                                    else:
                                        from services.web.auth import DashboardAuthManager
                                        cookie = request.cookies.get("syncink_session")
                                        if not cookie:
                                            auth_header = request.headers.get("Authorization")
                                            if auth_header and auth_header.startswith("Bearer "):
                                                cookie = auth_header.split(" ")[1]
                                        user = await DashboardAuthManager.get_instance().get_session(cookie) if cookie else None
                                        if user and user.get("discord_user_id") and user.get("discord_user_id") != 999888777:
                                            uid = user["discord_user_id"]
                                            guild = bot.get_guild(g_id) if bot else None
                                            is_admin = DashboardAuthManager.is_system_admin(uid, bot)
                                            is_member = (guild and guild.get_member(uid) is not None) if guild else False
                                            if not is_member and guild:
                                                try:
                                                    member = await guild.fetch_member(uid)
                                                    is_member = member is not None
                                                except Exception:
                                                    is_member = False
                                            if is_admin or is_member:
                                                self._socket_guild_subscriptions[ws] = g_id
                                                await self.send_guild_snapshot(ws, g_id, bot)
                                            else:
                                                await ws.send_json({"event": "error", "message": "Unauthorized subscription to server"})
                                        else:
                                            await ws.send_json({"event": "error", "message": "Authentication required to subscribe to server playback"})
                                except (ValueError, TypeError):
                                    pass

                        elif msg_type == "ping":
                            await ws.send_json({"event": "pong", "time": time.time()})

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
        guild = bot.get_guild(guild_id) if bot else None

        # Demo Guild 1: SyncInk Cyber Lounge
        if str(guild_id) == "110000000000000001" and not guild:
            return {
                "guild_id": "110000000000000001",
                "server_name": "SyncInk Cyber Lounge",
                "server_icon": "static/syncink-main.jpg",
                "voice_channel": "Lofi Chill & Beats",
                "channel_id": "90000000000000001",
                "is_connected": True,
                "is_playing": True,
                "is_paused": False,
                "volume": 85,
                "repeat_mode": "off",
                "autoplay": True,
                "is_247": True,
                "position": 45.0,
                "duration": 210,
                "current_track": {
                    "title": "Midnight City Vibes",
                    "clean_title": "Midnight City Vibes",
                    "author": "Lofi Fruit & Chill",
                    "thumbnail": "https://images.unsplash.com/photo-1518609878373-06d740f60d8b?w=400",
                    "duration": 210,
                    "formatted_duration": "03:30",
                    "platform": "youtube",
                    "is_radio": False,
                    "is_live": False,
                    "requested_by": "SyncInk Listener"
                },
                "queue": [
                    {
                        "title": "Coffee Shop Rain",
                        "author": "Chillhop Music",
                        "duration": 185,
                        "formatted_duration": "03:05",
                        "platform": "youtube",
                        "thumbnail": "https://images.unsplash.com/photo-1501386761578-eac5c94b800a?w=400"
                    },
                    {
                        "title": "Sunset Horizon",
                        "author": "Synthwave Collective",
                        "duration": 240,
                        "formatted_duration": "04:00",
                        "platform": "youtube",
                        "thumbnail": "https://images.unsplash.com/photo-1514525253161-7a46d19cd819?w=400"
                    }
                ],
                "active_radio": None,
                "active_radio_info": None,
                "autoplay_meta": {
                    "reason": "Recommended because your recent history shows high affinity for Chillhop and Lo-Fi beats.",
                    "genre": "Lo-Fi Beats",
                    "confidence": 0.96
                },
                "prefetched_track": {
                    "title": "Coffee Shop Rain",
                    "author": "Chillhop Music",
                    "thumbnail": "https://images.unsplash.com/photo-1501386761578-eac5c94b800a?w=400"
                },
                "listeners": 5,
                "voice_latency": 18.5,
                "latency_ms": 18.5,
                "server_time": time.time()
            }

        # Demo Guild 2: Vibrant Anime Cafe
        if str(guild_id) == "110000000000000002" and not guild:
            return {
                "guild_id": "110000000000000002",
                "server_name": "Vibrant Anime Cafe",
                "server_icon": "static/syncink-main.jpg",
                "voice_channel": "J-Rock Radio 24/7",
                "channel_id": "90000000000000002",
                "is_connected": True,
                "is_playing": True,
                "is_paused": False,
                "volume": 75,
                "repeat_mode": "off",
                "autoplay": True,
                "is_247": True,
                "position": 0.0,
                "duration": 0,
                "current_track": {
                    "title": "Anime J-Pop FM Live",
                    "clean_title": "Anime J-Pop FM Live",
                    "author": "Tokyo Live Radio",
                    "thumbnail": "https://images.unsplash.com/photo-1578632767115-351597cf2477?w=400",
                    "duration": 0,
                    "formatted_duration": "LIVE",
                    "platform": "radio",
                    "is_radio": True,
                    "is_live": True,
                    "requested_by": "Audia AI"
                },
                "queue": [],
                "active_radio": "Anime J-Pop FM Live",
                "active_radio_info": {
                    "name": "Anime J-Pop FM Live",
                    "country": "Japan",
                    "tags": "j-pop, anime, rock",
                    "bitrate": 192
                },
                "autoplay_meta": None,
                "prefetched_track": None,
                "listeners": 12,
                "voice_latency": 22.1,
                "latency_ms": 22.1,
                "server_time": time.time()
            }

        service = MusicService.get_instance()
        queue = service.get_queue(guild_id)
        current = queue.current_track

        guild = bot.get_guild(guild_id) if bot else None
        vc = (guild.voice_client if guild else None) or queue.voice_client

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

        position = queue.get_playback_time() if (is_playing or is_paused) else 0.0

        upcoming = []
        for t in queue.tracks[:25]:
            upcoming.append({
                "title": t.clean_title,
                "author": t.author,
                "url": t.url,
                "thumbnail": t.thumbnail,
                "duration": t.duration,
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
        channel_name = None
        channel_id = None
        if vc and vc.channel:
            listeners_count = len([m for m in vc.channel.members if not m.bot])
            channel_name = vc.channel.name
            channel_id = str(vc.channel.id)

        server_name = guild.name if guild else f"Guild #{guild_id}"
        server_icon = str(guild.icon.url) if (guild and guild.icon) else "static/syncink-main.jpg"

        # AutoPlay / Audia AI Metadata
        autoplay_meta = getattr(queue, "last_autoplay_meta", None)
        prefetched = getattr(queue, "prefetched_autoplay_track", None)
        prefetched_data = None
        if prefetched:
            prefetched_data = {
                "title": prefetched.clean_title,
                "author": prefetched.author,
                "thumbnail": prefetched.thumbnail
            }

        latency_ms = None
        if vc and is_connected:
            lat = getattr(vc, 'latency', None) or getattr(vc, 'average_latency', None)
            if isinstance(lat, (int, float)) and lat > 0:
                latency_ms = round(float(lat) * 1000, 1)
            elif bot and hasattr(bot, 'latency') and isinstance(bot.latency, (int, float)) and bot.latency > 0:
                latency_ms = round(float(bot.latency) * 1000, 1)
        elif bot and hasattr(bot, 'latency') and isinstance(bot.latency, (int, float)) and bot.latency > 0:
            latency_ms = round(float(bot.latency) * 1000, 1)

        return {
            "guild_id": str(guild_id),
            "server_name": server_name,
            "server_icon": server_icon,
            "connected": is_connected,
            "channel_name": channel_name,
            "channel_id": channel_id,
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
            "active_radio_info": queue.active_radio_station_info,
            "queue": upcoming,
            "queue_size": len(queue.tracks),
            "autoplay_meta": autoplay_meta,
            "prefetched_track": prefetched_data,
            "voice_latency": latency_ms,
            "latency_ms": latency_ms,
            "server_time": time.time()
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
        """Broadcasts playback state updates to all subscribed web clients in <1 second."""
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

def notify_guild_playback_changed(guild_id: int, bot: Any):
    """Safe, non-blocking dispatcher to push live updates to the web dashboard."""
    try:
        mgr = DashboardWebSocketManager.get_instance()
        loop = None
        if bot and hasattr(bot, "loop") and bot.loop and bot.loop.is_running():
            loop = bot.loop
        else:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
        if loop and loop.is_running():
            loop.create_task(mgr.broadcast_playback_update(guild_id, bot))
    except Exception as e:
        log.debug(f"[Dashboard WS Notify] {e}")

