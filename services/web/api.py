import os
import time
import json
import random
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from types import SimpleNamespace
import aiohttp.web
from database import db
from utils.logger import log
from services.web.auth import DashboardAuthManager
from services.web.websocket import DashboardWebSocketManager
from services.music_service import MusicService, Track
from services.radio_service import RadioService
from services.autoplay_service import AutoPlayService
from services.settings_service import SettingsService
from services.spotify.auth import SpotifyUserAuthManager

class DashboardAPI:
    """Production REST API powering the SyncInk Radio Unified Web Platform."""

    @staticmethod
    async def get_session_user(request: aiohttp.web.Request) -> Optional[Dict[str, Any]]:
        cookie = request.cookies.get("syncink_session")
        if not cookie:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                cookie = auth_header.split(" ")[1]
        if not cookie:
            return None
        return await DashboardAuthManager.get_instance().get_session(cookie)

    # ------------------ 1. Authentication & User Profile ------------------

    @classmethod
    def get_effective_redirect_uri(cls, request: aiohttp.web.Request) -> str:
        """Resolves the canonical Discord OAuth2 redirect URI matching Discord Developer Portal."""
        # 1. Environment variable override
        env_uri = os.getenv("DISCORD_REDIRECT_URI")
        if env_uri:
            return env_uri

        # 2. Check if request is forwarded from Cloudflare or production domain
        is_cf = bool(request.headers.get("CF-Ray") or request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-Host"))
        host = (request.headers.get("X-Forwarded-Host") or request.host or "").lower()

        # 3. Pure local offline development without reverse proxy
        if not is_cf and (host.startswith("localhost") or host.startswith("127.0.0.1")):
            proto = request.headers.get("X-Forwarded-Proto") or request.scheme or "http"
            is_subpath = request.path.startswith("/dashboard/radio")
            sub = "/dashboard/radio" if is_subpath else ""
            return f"{proto}://{host}{sub}/api/auth/discord/callback"

        # 4. Standard public production redirect URI registered in Discord Developer Portal
        return "https://syncink.site/dashboard/radio/api/auth/discord/callback"

    @classmethod
    async def handle_login(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        auth_mgr = DashboardAuthManager.get_instance()
        req_redirect = cls.get_effective_redirect_uri(request)
        login_url = auth_mgr.get_login_url(redirect_uri=req_redirect)
        log.info(f"[Dashboard API] Initiating Discord OAuth login with redirect_uri: {req_redirect}")
        raise aiohttp.web.HTTPFound(login_url)

    @classmethod
    async def handle_oauth_callback(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        code = request.query.get("code")
        error = request.query.get("error")
        is_subpath = (
            request.path.startswith("/dashboard/radio")
            or request.headers.get("X-Forwarded-Prefix") == "/dashboard/radio"
            or "dashboard/radio" in str(request.headers.get("Referer", ""))
        )
        base_prefix = "/dashboard/radio" if is_subpath else ""

        if error or not code:
            log.warning(f"[Dashboard API] OAuth callback error: {error}")
            raise aiohttp.web.HTTPFound(f"{base_prefix}/#overview?auth_error=" + (error or "missing_code"))

        auth_mgr = DashboardAuthManager.get_instance()
        req_redirect = cls.get_effective_redirect_uri(request)

        token_data = await auth_mgr.exchange_code(code, redirect_uri=req_redirect)
        if not token_data or "access_token" not in token_data:
            raise aiohttp.web.HTTPFound(f"{base_prefix}/#overview?auth_error=token_exchange_failed")

        user_data = await auth_mgr.fetch_user(token_data["access_token"])
        if not user_data:
            raise aiohttp.web.HTTPFound(f"{base_prefix}/#overview?auth_error=fetch_user_failed")

        session_id = await auth_mgr.create_session(user_data, token_data)

        # Ensure default preferences exist
        try:
            await db.execute(
                """
                INSERT INTO user_preferences (discord_user_id) VALUES ($1)
                ON CONFLICT (discord_user_id) DO NOTHING;
                """,
                int(user_data["id"])
            )
        except Exception:
            pass

        response = aiohttp.web.HTTPFound(f"{base_prefix}/#overview")
        response.set_cookie(
            "syncink_session",
            session_id,
            max_age=30 * 86400,
            httponly=True,
            samesite="Lax",
            path="/",
            secure=request.scheme == "https"
        )
        return response

    @classmethod
    async def handle_me(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"authenticated": False, "user": None})

        user_id = user["discord_user_id"]
        bot = request.app.get("bot")
        is_admin = DashboardAuthManager.is_system_admin(user_id, bot)

        avatar_url = None
        if user.get("avatar"):
            avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{user['avatar']}.png?size=256"
        else:
            avatar_url = "static/radio-bot.jpg"

        prefs_row = await db.fetchrow("SELECT * FROM user_preferences WHERE discord_user_id = $1", user_id)
        prefs = dict(prefs_row) if prefs_row else {
            "timezone": "UTC",
            "language": "en",
            "private_listening": False,
            "theme": "dark"
        }

        return aiohttp.web.json_response({
            "authenticated": True,
            "user": {
                "id": str(user_id),
                "username": user.get("username"),
                "discriminator": user.get("discriminator", "0"),
                "avatar_url": avatar_url,
                "is_admin": is_admin,
                "preferences": prefs
            }
        })

    @classmethod
    async def handle_logout(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        cookie = request.cookies.get("syncink_session")
        if cookie:
            await DashboardAuthManager.get_instance().destroy_session(cookie)

        response = aiohttp.web.json_response({"success": True})
        response.del_cookie("syncink_session")
        return response

    @classmethod
    async def handle_demo_auth(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """Toggles a rich demo session for instant local UI evaluation."""
        auth_mgr = DashboardAuthManager.get_instance()
        current_user = await cls.get_session_user(request)
        if current_user and current_user.get("discord_user_id") == 999888777:
            cookie = request.cookies.get("syncink_session")
            if cookie:
                await auth_mgr.destroy_session(cookie)
            resp = aiohttp.web.json_response({"success": True, "message": "Demo mode deactivated.", "authenticated": False})
            resp.del_cookie("syncink_session", path="/")
            return resp

        demo_user = {
            "id": "999888777",
            "username": "SyncInk Listener",
            "discriminator": "0001",
            "avatar": None,
            "email": "demo@syncink.site"
        }
        demo_token = {
            "access_token": "demo_preview_token",
            "expires_in": 7 * 86400
        }
        session_id = await auth_mgr.create_session(demo_user, demo_token)

        try:
            await db.execute(
                """
                INSERT INTO user_preferences (discord_user_id, timezone, language, private_listening, theme)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (discord_user_id) DO NOTHING;
                """,
                999888777, "UTC", "en", False, "dark"
            )
        except Exception:
            pass

        resp = aiohttp.web.json_response({
            "success": True,
            "message": "Demo mode activated! Exploring as SyncInk Listener.",
            "authenticated": True,
            "user": {
                "id": "999888777",
                "username": "SyncInk Listener",
                "discriminator": "0001",
                "avatar_url": "static/radio-bot.jpg",
                "is_admin": True
            }
        })
        resp.set_cookie(
            "syncink_session",
            session_id,
            max_age=7 * 86400,
            httponly=True,
            samesite="Lax",
            path="/"
        )
        return resp

    @classmethod
    async def handle_get_preferences(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        user_id = user["discord_user_id"]
        prefs_row = await db.fetchrow("SELECT * FROM user_preferences WHERE discord_user_id = $1", user_id)
        prefs = dict(prefs_row) if prefs_row else {
            "timezone": "UTC",
            "language": "en",
            "private_listening": False,
            "theme": "dark"
        }
        return aiohttp.web.json_response(prefs)

    @classmethod
    async def handle_update_preferences(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        user_id = user["discord_user_id"]
        body = await request.json()

        timezone = body.get("timezone", "UTC")
        language = body.get("language", "en")
        private_listening = 1 if body.get("private_listening") else 0
        theme = body.get("theme", "dark")

        query = """
            INSERT INTO user_preferences (discord_user_id, timezone, language, private_listening, theme, updated_at)
            VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
            ON CONFLICT (discord_user_id) DO UPDATE SET
                timezone = EXCLUDED.timezone,
                language = EXCLUDED.language,
                private_listening = EXCLUDED.private_listening,
                theme = EXCLUDED.theme,
                updated_at = CURRENT_TIMESTAMP;
        """
        await db.execute(query, user_id, timezone, language, private_listening, theme)
        return aiohttp.web.json_response({"success": True})

    # ------------------ 2. Discord Servers & Playback Control ------------------

    @classmethod
    def _get_demo_servers(cls) -> List[Dict[str, Any]]:
        return [
            {
                "id": "110000000000000001",
                "name": "SyncInk Cyber Lounge (Demo)",
                "icon": "static/radio-bot.jpg",
                "member_count": 142,
                "connected": True,
                "voice_channel": "Lofi Chill & Beats",
                "voice_channel_id": "90000000000000001",
                "listeners": 5,
                "current_track": "Midnight City Vibes",
                "radio_station": None,
                "is_playing": True,
                "permission": "owner",
                "can_manage": True
            },
            {
                "id": "110000000000000002",
                "name": "Vibrant Anime Cafe (Demo)",
                "icon": "static/radio-bot.jpg",
                "member_count": 89,
                "connected": True,
                "voice_channel": "J-Rock Radio 24/7",
                "voice_channel_id": "90000000000000002",
                "listeners": 12,
                "current_track": "Anime J-Pop FM Live",
                "radio_station": "Anime J-Pop FM Live",
                "is_playing": True,
                "permission": "admin",
                "can_manage": True
            }
        ]

    @classmethod
    async def handle_get_servers(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({
                "authenticated": False,
                "error": "Authentication required. Please log in with Discord.",
                "servers": []
            }, status=401)

        # Isolated demo user only gets mock demo servers
        if user.get("discord_user_id") == 999888777:
            return aiohttp.web.json_response({
                "authenticated": True,
                "servers": cls._get_demo_servers()
            })

        bot = request.app.get("bot")
        user_id = user["discord_user_id"]
        is_sys_admin = DashboardAuthManager.is_system_admin(user_id, bot)

        user_guild_ids = set()
        user_guilds_map = {}

        if user.get("access_token"):
            auth_mgr = DashboardAuthManager.get_instance()
            guilds = await auth_mgr.fetch_user_guilds(user["access_token"])
            for g in guilds:
                gid = int(g["id"])
                user_guild_ids.add(gid)
                user_guilds_map[gid] = g

        server_list = []
        if bot:
            for g in bot.guilds:
                # User MUST be a member of this guild, unless they are the bot system administrator
                is_member = (g.id in user_guild_ids)
                if not is_member and not is_sys_admin:
                    continue

                icon_url = str(g.icon.url) if g.icon else "static/radio-bot.jpg"
                queue = MusicService.get_instance().get_queue(g.id)
                vc = g.voice_client

                perm = "listener"
                can_manage = False

                member = g.get_member(user_id)
                if not member:
                    try:
                        member = await g.fetch_member(user_id)
                    except Exception:
                        member = None

                if is_sys_admin or g.owner_id == user_id:
                    perm = "owner"
                    can_manage = True
                elif member and member.guild_permissions.administrator:
                    perm = "admin"
                    can_manage = True
                elif member and (member.guild_permissions.manage_guild or member.guild_permissions.manage_channels):
                    perm = "dj"
                    can_manage = True
                elif g.id in user_guilds_map:
                    raw_perms = int(user_guilds_map[g.id].get("permissions", 0))
                    if (raw_perms & 0x8) != 0:
                        perm = "admin"
                        can_manage = True
                    elif (raw_perms & 0x20) != 0:
                        perm = "dj"
                        can_manage = True

                latency_ms = None
                if vc and vc.is_connected():
                    lat = getattr(vc, 'latency', None) or getattr(vc, 'average_latency', None)
                    if isinstance(lat, (int, float)) and lat > 0:
                        latency_ms = round(float(lat) * 1000, 1)
                    elif bot and hasattr(bot, 'latency') and isinstance(bot.latency, (int, float)) and bot.latency > 0:
                        latency_ms = round(float(bot.latency) * 1000, 1)
                elif bot and hasattr(bot, 'latency') and isinstance(bot.latency, (int, float)) and bot.latency > 0:
                    latency_ms = round(float(bot.latency) * 1000, 1)

                server_list.append({
                    "id": str(g.id),
                    "name": g.name,
                    "icon": icon_url,
                    "member_count": g.member_count,
                    "connected": bool(vc and vc.is_connected()),
                    "voice_channel": vc.channel.name if vc and vc.channel else None,
                    "voice_channel_id": str(vc.channel.id) if vc and vc.channel else None,
                    "listeners": len([m for m in vc.channel.members if not m.bot]) if vc and vc.channel else 0,
                    "current_track": queue.current_track.clean_title if queue.current_track else None,
                    "radio_station": queue.active_radio_station_info.get("name") if queue.active_radio_station_info else queue.active_radio_station,
                    "is_playing": bool(vc and vc.is_playing()),
                    "permission": perm,
                    "can_manage": can_manage,
                    "latency_ms": latency_ms,
                    "voice_latency": latency_ms
                })

        return aiohttp.web.json_response({"authenticated": True, "servers": server_list})

    @classmethod
    async def handle_get_server_detail(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        guild_id_str = request.match_info.get("guild_id")
        try:
            guild_id = int(guild_id_str)
        except (ValueError, TypeError):
            return aiohttp.web.json_response({"error": "Invalid guild_id"}, status=400)

        # Allow demo guilds
        if str(guild_id).startswith("110000"):
            bot = request.app.get("bot")
            state = DashboardWebSocketManager.get_instance().serialize_guild_playback(guild_id, bot)
            return aiohttp.web.json_response(state)

        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        user_id = user["discord_user_id"]
        if user_id == 999888777:
            return aiohttp.web.json_response({"error": "Demo mode cannot view real Discord servers"}, status=403)

        bot = request.app.get("bot")
        guild = bot.get_guild(guild_id) if bot else None
        if not guild:
            return aiohttp.web.json_response({"error": "Guild not found on bot instance"}, status=404)

        is_admin = DashboardAuthManager.is_system_admin(user_id, bot)
        member = guild.get_member(user_id)
        if not member and not is_admin:
            try:
                member = await guild.fetch_member(user_id)
            except Exception:
                member = None

        if not member and not is_admin:
            return aiohttp.web.json_response({"error": "Forbidden: You are not a member of this Discord server"}, status=403)

        state = DashboardWebSocketManager.get_instance().serialize_guild_playback(guild_id, bot)
        return aiohttp.web.json_response(state)

    @classmethod
    async def _send_discord_player_card(cls, bot, guild, queue, track=None, is_enqueued=False, enqueued_position=1):
        """Ensures Discord channel has the rich interactive player card when playback is initiated via Web Dashboard."""
        if not bot or not guild:
            return
        music_cog = bot.get_cog("Music")
        if not music_cog:
            return

        # Check if guild has a configured dedicated music text channel
        target_ch = None
        try:
            from services.settings_service import SettingsService
            settings = await SettingsService.get_guild_settings(guild.id)
            cid = settings.get("music_channel_id")
            if cid:
                ch = guild.get_channel(int(cid))
                if ch and ch.permissions_for(guild.me).send_messages:
                    target_ch = ch
        except Exception as se:
            log.debug(f"[API] Could not resolve dedicated music channel: {se}")

        if target_ch:
            queue.text_channel = target_ch
        elif not queue.text_channel or queue.text_channel.guild.id != guild.id:
            preferred_names = ["music", "bot-commands", "commands", "radio", "music-bot", "general", "bot", "chat"]
            for name in preferred_names:
                for ch in guild.text_channels:
                    if ch.name.lower() == name and ch.permissions_for(guild.me).send_messages:
                        target_ch = ch
                        break
                if target_ch:
                    break

            if not target_ch and guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
                target_ch = guild.system_channel

            if not target_ch:
                for ch in guild.text_channels:
                    if ch.permissions_for(guild.me).send_messages:
                        target_ch = ch
                        break

            if target_ch:
                queue.text_channel = target_ch

        if not queue.text_channel:
            return

        try:
            from cogs.music import MusicPlayerLayoutView, TrackEnqueuedLayoutView
            if is_enqueued and track:
                view = TrackEnqueuedLayoutView(track, position=enqueued_position)
                await queue.text_channel.send(view=view)
            else:
                if queue.now_playing_message:
                    try:
                        await queue.now_playing_message.delete()
                    except Exception:
                        pass
                    queue.now_playing_message = None

                view = MusicPlayerLayoutView(music_cog, queue)
                queue.now_playing_message = await queue.text_channel.send(view=view)
        except Exception as e:
            log.warning(f"[Dashboard Discord Player Card Error] {e}")

    @classmethod
    async def handle_server_control(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        guild_id_str = request.match_info.get("guild_id")
        try:
            guild_id = int(guild_id_str)
        except (ValueError, TypeError):
            return aiohttp.web.json_response({"error": "Invalid guild_id"}, status=400)

        try:
            body = await request.json()
        except Exception:
            return aiohttp.web.json_response({"error": "Invalid JSON body"}, status=400)

        action = body.get("action")
        if str(guild_id).startswith("110000"):
            return aiohttp.web.json_response({
                "success": True,
                "message": f"Demo action '{action}' executed successfully on server {guild_id}",
                "server_id": str(guild_id)
            })

        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required to control playback"}, status=401)

        user_id = user["discord_user_id"]
        if user_id == 999888777:
            return aiohttp.web.json_response({"error": "Demo mode cannot control real Discord servers"}, status=403)

        bot = request.app.get("bot")
        guild = bot.get_guild(guild_id) if bot else None
        if not guild:
            return aiohttp.web.json_response({"error": "Server not found on bot instance"}, status=404)

        # STRICT SERVER-SIDE PERMISSION VERIFICATION
        is_admin = DashboardAuthManager.is_system_admin(user_id, bot)
        can_manage = DashboardAuthManager.can_manage_guild(user_id, guild)
        member = guild.get_member(user_id)
        if not member and not (is_admin or can_manage):
            try:
                member = await guild.fetch_member(user_id)
            except Exception:
                member = None

        in_voice = False
        if member and member.voice and member.voice.channel:
            vc = guild.voice_client
            if not vc or not vc.is_connected() or (vc.channel and vc.channel.id == member.voice.channel.id):
                in_voice = True

        if not (is_admin or can_manage or in_voice):
            return aiohttp.web.json_response({
                "error": "Forbidden: You must be a Server Manager, DJ, or connected to the bot's voice channel in Discord to control playback"
            }, status=403)

        service = MusicService.get_instance()
        queue = service.get_queue(guild_id)
        vc = (guild.voice_client if guild else None) or queue.voice_client

        if action == "play":
            query = body.get("query")
            if not query:
                return aiohttp.web.json_response({"error": "Missing query parameter"}, status=400)

            voice_channel_id = body.get("voice_channel_id")
            requester = member or SimpleNamespace(
                id=user_id,
                name=user.get("username", "Dashboard User"),
                display_name=user.get("username", "Dashboard User"),
                mention=f"<@{user_id}>",
                bot=False,
            )

            # Start track extraction immediately in parallel with voice connection!
            search_task = asyncio.create_task(service.search_and_extract(query, requester, limit=1))

            if (not vc or not vc.is_connected()) and guild:
                target_vc = None
                if voice_channel_id:
                    target_vc = guild.get_channel(int(voice_channel_id))
                elif member and member.voice and member.voice.channel:
                    target_vc = member.voice.channel
                elif guild.voice_channels:
                    for ch in guild.voice_channels:
                        if any(not m.bot for m in ch.members):
                            target_vc = ch
                            break
                    if not target_vc:
                        target_vc = guild.voice_channels[0]
                if target_vc:
                    try:
                        vc = await target_vc.connect(self_deaf=True, timeout=15.0, reconnect=True)
                        queue.voice_client = vc
                    except Exception as ce:
                        log.warning(f"Voice connect error: {ce}")

            try:
                tracks = await search_task
                if tracks:
                    track = tracks[0]
                    track.requested_by = requester
                    if not queue.current_track:
                        music_cog = bot.get_cog("Music") if bot else None
                        if music_cog:
                            await music_cog.play_track(queue, track)
                            asyncio.create_task(cls._send_discord_player_card(bot, guild, queue, track, is_enqueued=False))
                    else:
                        queue.tracks.append(track)
                        asyncio.create_task(cls._send_discord_player_card(bot, guild, queue, track, is_enqueued=True, enqueued_position=len(queue.tracks)))
            except Exception as pe:
                if not search_task.done():
                    search_task.cancel()
                return aiohttp.web.json_response({"error": f"Failed to enqueue: {pe}"}, status=500)

        elif action == "pause":
            if vc and vc.is_playing():
                vc.pause()
                queue.paused_at = time.time()

        elif action == "resume":
            if vc and vc.is_paused():
                vc.resume()
                if queue.paused_at is not None:
                    queue.total_paused_duration += (time.time() - queue.paused_at)
                    queue.paused_at = None

        elif action == "skip":
            if queue.current_track:
                is_radio = queue.current_track.is_radio or queue.current_track.platform == "radio" or bool(queue.active_radio_station)
                if is_radio:
                    music_cog = bot.get_cog("Music") if bot else None
                    if music_cog:
                        await music_cog.skip_to_next_radio_station(queue)
                else:
                    queue.manual_skip = True
                    if vc:
                        vc.stop()

        elif action == "previous":
            if queue.history:
                prev = queue.history.pop()
                if queue.current_track:
                    queue.tracks.insert(0, queue.current_track)
                queue.tracks.insert(0, prev)
                queue.manual_skip = True
                if vc:
                    vc.stop()

        elif action == "stop":
            queue.tracks.clear()
            queue.active_radio_station = None
            queue.active_radio_station_info = None
            queue.active_country_stations = None
            queue.autoplay = False
            queue.current_track = None
            if vc:
                vc.stop()

        elif action == "volume":
            vol = body.get("volume")
            if vol is not None:
                val = max(1, min(150, int(vol)))
                queue.volume = val
                if vc and vc.source:
                    curr = vc.source
                    while curr:
                        if hasattr(curr, "volume"):
                            try:
                                curr.volume = val / 100.0
                            except Exception:
                                pass
                        curr = getattr(curr, "original", None) or getattr(curr, "_source", None) or getattr(curr, "source", None)

        elif action == "loop":
            mode = body.get("mode", "off")
            if mode in ("off", "track", "queue"):
                queue.repeat_mode = mode

        elif action == "shuffle":
            random.shuffle(queue.tracks)

        elif action == "autoplay":
            queue.autoplay = bool(body.get("enabled", not queue.autoplay))
            if queue.autoplay:
                AutoPlayService.get_instance().trigger_prefetch(queue, service)
            else:
                queue.prefetched_autoplay_track = None
                queue.prefetched_autoplay_meta = None

        elif action == "remove_track":
            index = body.get("index")
            if index is not None and 0 <= index < len(queue.tracks):
                queue.tracks.pop(index)

        elif action == "clear_queue":
            queue.tracks.clear()

        # Real-time WebSocket broadcast in <1 second
        await DashboardWebSocketManager.get_instance().broadcast_playback_update(guild_id, bot)
        state = DashboardWebSocketManager.get_instance().serialize_guild_playback(guild_id, bot)
        return aiohttp.web.json_response({"success": True, "state": state})

    @classmethod
    async def handle_get_server_settings(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        guild_id_str = request.match_info.get("guild_id")
        try:
            guild_id = int(guild_id_str)
        except (ValueError, TypeError):
            return aiohttp.web.json_response({"error": "Invalid guild_id"}, status=400)

        if str(guild_id).startswith("110000"):
            return aiohttp.web.json_response({
                "guild_id": str(guild_id),
                "can_manage": True,
                "music_channel_id": None,
                "default_voice_channel_id": None,
                "dj_role_id": None,
                "max_volume": 100,
                "autoplay_enabled": True,
                "is_247": True,
                "announcements_enabled": True,
                "playback_notifications": True,
                "server_language": "en",
                "preferred_radio_country": "India",
                "audia_genre": "Lo-Fi",
                "audia_mood": "Chill",
                "available_roles": [],
                "available_channels": [],
                "available_voice_channels": [],
            })

        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        user_id = user["discord_user_id"]
        if user_id == 999888777:
            return aiohttp.web.json_response({"error": "Demo mode cannot view real server settings"}, status=403)

        bot = request.app.get("bot")
        guild = bot.get_guild(guild_id) if bot else None
        if not guild:
            return aiohttp.web.json_response({"error": "Guild not found on bot instance"}, status=404)

        is_admin = DashboardAuthManager.is_system_admin(user_id, bot)
        can_manage = DashboardAuthManager.can_manage_guild(user_id, guild)
        if not is_admin and not can_manage:
            return aiohttp.web.json_response({
                "error": "Forbidden: You do not have permission to view or manage settings for this server"
            }, status=403)

        row = await db.fetchrow("SELECT * FROM guild_settings WHERE guild_id = $1", guild_id)
        settings = dict(row) if row else {}

        roles = []
        channels = []
        voice_channels = []
        if guild:
            for r in guild.roles:
                if not r.is_default():
                    roles.append({"id": str(r.id), "name": r.name, "color": f"#{r.color.value:06x}"})
            for c in guild.text_channels:
                channels.append({"id": str(c.id), "name": c.name})
            for vc in guild.voice_channels:
                voice_channels.append({"id": str(vc.id), "name": vc.name})

        return aiohttp.web.json_response({
            "guild_id": str(guild_id),
            "can_manage": can_manage,
            "music_channel_id": str(settings.get("music_channel_id")) if settings.get("music_channel_id") else None,
            "default_voice_channel_id": str(settings.get("default_voice_channel_id")) if settings.get("default_voice_channel_id") else None,
            "dj_role_id": str(settings.get("dj_role_id")) if settings.get("dj_role_id") else None,
            "max_volume": settings.get("max_volume", 100),
            "autoplay_enabled": bool(settings.get("autoplay_enabled", 1)),
            "is_247": bool(settings.get("is_247", 0)),
            "announcements_enabled": bool(settings.get("announcements_enabled", 1)),
            "playback_notifications": bool(settings.get("playback_notifications", 1)),
            "server_language": settings.get("server_language", "en"),
            "preferred_radio_country": settings.get("preferred_radio_country", "India"),
            "audia_genre": settings.get("audia_genre"),
            "audia_mood": settings.get("audia_mood"),
            "available_roles": roles,
            "available_channels": channels,
            "available_voice_channels": voice_channels,
        })

    @classmethod
    async def handle_update_server_settings(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        guild_id_str = request.match_info.get("guild_id")
        try:
            guild_id = int(guild_id_str)
        except (ValueError, TypeError):
            return aiohttp.web.json_response({"error": "Invalid guild_id"}, status=400)

        if str(guild_id).startswith("110000"):
            return aiohttp.web.json_response({"success": True})

        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        user_id = user["discord_user_id"]
        if user_id == 999888777:
            return aiohttp.web.json_response({"error": "Demo mode cannot modify real server settings"}, status=403)

        bot = request.app.get("bot")
        guild = bot.get_guild(guild_id) if bot else None
        if not guild:
            return aiohttp.web.json_response({"error": "Guild not found on bot instance"}, status=404)

        # STRICT SERVER-SIDE PERMISSION VERIFICATION
        is_admin = DashboardAuthManager.is_system_admin(user_id, bot)
        can_manage = DashboardAuthManager.can_manage_guild(user_id, guild)
        if not is_admin and not can_manage:
            return aiohttp.web.json_response({"error": "Forbidden: You do not have permission to manage this server"}, status=403)

        body = await request.json()
        music_channel_id = int(body.get("music_channel_id")) if body.get("music_channel_id") else None
        default_voice_channel_id = int(body.get("default_voice_channel_id")) if body.get("default_voice_channel_id") else None
        dj_role_id = int(body.get("dj_role_id")) if body.get("dj_role_id") else None
        max_volume = max(1, min(150, int(body.get("max_volume", 100))))
        autoplay_enabled = 1 if body.get("autoplay_enabled", True) else 0
        is_247 = 1 if body.get("is_247", False) else 0
        announcements_enabled = 1 if body.get("announcements_enabled", True) else 0
        playback_notifications = 1 if body.get("playback_notifications", True) else 0
        server_language = body.get("server_language", "en")
        preferred_radio_country = body.get("preferred_radio_country", "India")
        audia_genre = body.get("audia_genre")
        audia_mood = body.get("audia_mood")

        query = """
            INSERT INTO guild_settings (
                guild_id, music_channel_id, default_voice_channel_id, dj_role_id,
                max_volume, autoplay_enabled, is_247, announcements_enabled,
                playback_notifications, server_language, preferred_radio_country,
                audia_genre, audia_mood
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (guild_id) DO UPDATE SET
                music_channel_id = EXCLUDED.music_channel_id,
                default_voice_channel_id = EXCLUDED.default_voice_channel_id,
                dj_role_id = EXCLUDED.dj_role_id,
                max_volume = EXCLUDED.max_volume,
                autoplay_enabled = EXCLUDED.autoplay_enabled,
                is_247 = EXCLUDED.is_247,
                announcements_enabled = EXCLUDED.announcements_enabled,
                playback_notifications = EXCLUDED.playback_notifications,
                server_language = EXCLUDED.server_language,
                preferred_radio_country = EXCLUDED.preferred_radio_country,
                audia_genre = EXCLUDED.audia_genre,
                audia_mood = EXCLUDED.audia_mood;
        """
        await db.execute(
            query,
            guild_id, music_channel_id, default_voice_channel_id, dj_role_id,
            max_volume, autoplay_enabled, is_247, announcements_enabled,
            playback_notifications, server_language, preferred_radio_country,
            audia_genre, audia_mood
        )

        # Update active queue settings live
        queue = MusicService.get_instance().get_queue(guild_id)
        queue.is_247 = bool(is_247)
        if queue.volume > max_volume:
            queue.volume = max_volume

        return aiohttp.web.json_response({"success": True})

    # ------------------ 3. Global Radio Directory ------------------

    @classmethod
    async def handle_get_radio_countries(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        service = RadioService.get_instance()
        countries = service.get_countries()
        return aiohttp.web.json_response({"countries": countries})

    @classmethod
    async def handle_get_radio_stations(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        country = request.query.get("country", "India")
        genre = request.query.get("genre")
        query = request.query.get("query")
        sort = request.query.get("sort", "votes")
        limit = min(120, int(request.query.get("limit", 60)))

        service = RadioService.get_instance()
        stations = service.get_country_stations(country, limit=limit)

        if genre:
            genre_low = genre.lower()
            stations = [s for s in stations if genre_low in s.get("tags", "").lower()]

        if query:
            q_low = query.lower()
            stations = [
                s for s in stations
                if q_low in s.get("name", "").lower() or q_low in s.get("tags", "").lower()
            ]

        if sort == "votes":
            stations.sort(key=lambda x: x.get("votes", 0), reverse=True)
        elif sort == "bitrate":
            stations.sort(key=lambda x: x.get("bitrate", 0), reverse=True)
        elif sort == "name":
            stations.sort(key=lambda x: x.get("name", "").lower())

        clean_stations = []
        for s in stations[:limit]:
            clean_stations.append({
                "stationuuid": s.get("stationuuid") or s.get("name"),
                "name": s.get("name"),
                "url": s.get("url_resolved") or s.get("url"),
                "favicon": s.get("favicon") or "static/radio-bot.jpg",
                "country": s.get("country") or country,
                "tags": s.get("tags", ""),
                "votes": s.get("votes", 0),
                "bitrate": s.get("bitrate", 128),
                "codec": s.get("codec", "MP3"),
                "available": bool(s.get("lastcheckok", 1))
            })

        return aiohttp.web.json_response({"stations": clean_stations, "count": len(clean_stations)})

    @classmethod
    async def handle_get_popular_radio(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        service = RadioService.get_instance()
        stations = service.get_popular_stations(limit=40)
        return aiohttp.web.json_response({"stations": stations})

    @classmethod
    async def handle_get_trending_radio(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        service = RadioService.get_instance()
        stations = service.get_trending_stations(limit=40)
        return aiohttp.web.json_response({"stations": stations})

    @classmethod
    async def handle_get_radio_genres(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        service = RadioService.get_instance()
        genres = service.get_top_tags(limit=30)
        return aiohttp.web.json_response({"genres": genres})

    @classmethod
    async def handle_tune_radio(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        body = await request.json()
        guild_id_str = body.get("guild_id")
        station_name = body.get("station_name")
        country = body.get("country", "India")
        stream_url = body.get("url")

        if not guild_id_str or not stream_url:
            return aiohttp.web.json_response({"error": "Missing guild_id or station url"}, status=400)

        guild_id = int(guild_id_str)
        if str(guild_id).startswith("110000"):
            return aiohttp.web.json_response({"success": True, "station": station_name})

        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required to tune radio"}, status=401)

        user_id = user["discord_user_id"]
        if user_id == 999888777:
            return aiohttp.web.json_response({"error": "Demo mode cannot tune live radio"}, status=403)

        bot = request.app.get("bot")
        guild = bot.get_guild(guild_id) if bot else None
        if not guild:
            return aiohttp.web.json_response({"error": "Server not found on bot instance"}, status=404)

        is_admin = DashboardAuthManager.is_system_admin(user_id, bot)
        can_manage = DashboardAuthManager.can_manage_guild(user_id, guild)
        member = guild.get_member(user_id)
        if not member:
            try:
                member = await guild.fetch_member(user_id)
            except Exception:
                member = None

        in_voice = bool(member and member.voice and member.voice.channel)
        if not (is_admin or can_manage or in_voice):
            return aiohttp.web.json_response({
                "error": "Forbidden: You must be a Server Manager, DJ, or connected to the voice channel to tune radio"
            }, status=403)

        music_cog = bot.get_cog("Music") if bot else None
        if not music_cog:
            return aiohttp.web.json_response({"error": "Music service unavailable"}, status=503)

        service = MusicService.get_instance()
        queue = service.get_queue(guild_id)

        # Auto-connect if not connected
        guild = bot.get_guild(guild_id) if bot else None
        if guild and (not queue.voice_client or not queue.voice_client.is_connected()):
            for ch in guild.voice_channels:
                if any(not m.bot for m in ch.members):
                    try:
                        queue.voice_client = await ch.connect()
                        break
                    except Exception:
                        pass
            if not queue.voice_client and guild.voice_channels:
                try:
                    queue.voice_client = await guild.voice_channels[0].connect()
                except Exception:
                    pass

        station_dict = {
            "name": station_name or "Live Radio",
            "url": stream_url,
            "url_resolved": stream_url,
            "favicon": body.get("favicon", "static/radio-bot.jpg"),
            "country": country
        }

        from cogs.music import make_radio_track
        requester = member or SimpleNamespace(id=user_id, name=user.get("username", "Dashboard User"), display_name=user.get("username", "Dashboard User"), mention=f"<@{user_id}>", bot=False)
        track = make_radio_track(station_dict, country, requester)
        track.requested_by = requester
        queue.active_radio_station = country
        queue.active_radio_station_info = station_dict
        queue.tracks.clear()

        await music_cog.play_track(queue, track)
        await cls._send_discord_player_card(bot, guild, queue, track, is_enqueued=False)
        await DashboardWebSocketManager.get_instance().broadcast_playback_update(guild_id, bot)

        return aiohttp.web.json_response({"success": True, "station": station_name})

    # ------------------ 4. Audia AI Engine ------------------

    @classmethod
    async def handle_get_audia_profile(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        user_id = user["discord_user_id"] if user else 0

        prof = AutoPlayService.get_instance().get_user_profile(user_id)
        blocked_set = {str(b).strip().lower() for b in prof.blocked_artists if str(b).strip()}

        clean_artists = [
            {"artist": a, "affinity": round(score, 1)}
            for a, score in sorted(prof.artist_affinity.items(), key=lambda x: x[1], reverse=True)
            if a and score > 0 and str(a).strip().lower() not in blocked_set
            and not any(l in a.lower() for l in ["t-series", "sony music", "zee music", "tips", "yrf", "saregama"])
        ][:20]

        top_genres = [
            {"genre": g, "score": round(score, 1)}
            for g, score in sorted(prof.genre_affinity.items(), key=lambda x: x[1], reverse=True)[:10]
        ]

        return aiohttp.web.json_response({
            "discovery_mode": prof.discovery_mode,
            "manual_genre": prof.manual_genre,
            "manual_mood": prof.manual_mood,
            "manual_language": prof.manual_language,
            "top_artists": clean_artists,
            "top_genres": top_genres,
            "blocked_artists": list(prof.blocked_artists),
            "liked_count": len(prof.liked_tracks),
            "disliked_count": len(prof.disliked_tracks),
        })

    @classmethod
    async def handle_get_audia_recommendations(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user or not user.get("discord_user_id"):
            return aiohttp.web.json_response({
                "authenticated": False,
                "recommendations": [],
                "message": "Authentication required for personalized Audia AI recommendations"
            })

        user_id = user["discord_user_id"]
        recs = await AutoPlayService.get_instance().get_recommendations_for_user(user_id, limit=8)
        return aiohttp.web.json_response({
            "authenticated": True,
            "recommendations": recs
        })

    @classmethod
    async def handle_update_audia_settings(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        body = await request.json()
        prof = AutoPlayService.get_instance().get_user_profile(user["discord_user_id"])

        if "discovery_mode" in body:
            prof.discovery_mode = body["discovery_mode"]
        if "manual_genre" in body:
            prof.manual_genre = body["manual_genre"]
        if "manual_mood" in body:
            prof.manual_mood = body["manual_mood"]
        if "manual_language" in body:
            prof.manual_language = body["manual_language"]

        AutoPlayService.get_instance().save_profiles()
        return aiohttp.web.json_response({"success": True})

    @classmethod
    async def handle_audia_feedback(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        body = await request.json()
        action = body.get("action")  # like, dislike, block, unblock
        artist = body.get("artist")
        track_title = body.get("track_title")

        ap_svc = AutoPlayService.get_instance()
        prof = ap_svc.get_user_profile(user["discord_user_id"])
        msg = "Updated preference."
        if action == "block" and artist:
            _, msg, _ = ap_svc.block_artist(user["discord_user_id"], artist)
        elif action == "unblock" and artist:
            _, msg, _ = ap_svc.unblock_artist(user["discord_user_id"], artist)
        elif action in ("like", "dislike") and track_title:
            _, msg = ap_svc.record_explicit_feedback(
                int(user["discord_user_id"]),
                type("ObjTrack", (), {"clean_title": track_title, "title": track_title, "author": artist or ""})(),
                action
            )

        ap_svc.save_profiles()
        return aiohttp.web.json_response({
            "success": True,
            "action": action,
            "artist": artist,
            "message": msg,
            "blocked_artists": list(prof.blocked_artists),
        })

    # ------------------ 5. Library, Favorites & Playlists ------------------

    @classmethod
    async def handle_get_favorites(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"favorites": []})

        item_type = request.query.get("item_type")
        if item_type and item_type != "all":
            rows = await db.fetch(
                "SELECT * FROM user_favorites WHERE discord_user_id = $1 AND item_type = $2 ORDER BY created_at DESC",
                user["discord_user_id"], item_type
            )
        else:
            rows = await db.fetch(
                "SELECT * FROM user_favorites WHERE discord_user_id = $1 ORDER BY created_at DESC",
                user["discord_user_id"]
            )

        favs = [dict(r) for r in rows]
        for f in favs:
            if isinstance(f.get("created_at"), datetime):
                f["created_at"] = f["created_at"].isoformat()
        return aiohttp.web.json_response({"favorites": favs})

    @classmethod
    async def handle_add_favorite(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        body = await request.json()
        item_type = body.get("item_type", "song")
        item_id = body.get("item_id", "")
        title = body.get("title", "")
        subtitle = body.get("subtitle", "")
        image_url = body.get("image_url", "static/radio-bot.jpg")
        url = body.get("url", "")

        query = """
            INSERT INTO user_favorites (discord_user_id, item_type, item_id, title, subtitle, image_url, url)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (discord_user_id, item_type, item_id) DO NOTHING;
        """
        await db.execute(query, user["discord_user_id"], item_type, item_id, title, subtitle, image_url, url)
        return aiohttp.web.json_response({"success": True})

    @classmethod
    async def handle_remove_favorite(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        fav_id = request.match_info.get("id")
        await db.execute(
            "DELETE FROM user_favorites WHERE id = $1 AND discord_user_id = $2",
            int(fav_id), user["discord_user_id"]
        )
        return aiohttp.web.json_response({"success": True})

    @classmethod
    async def handle_get_playlists(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"playlists": []})

        rows = await db.fetch(
            """
            SELECT p.*, COUNT(t.id) as track_count
            FROM user_playlists p
            LEFT JOIN user_playlist_tracks t ON p.id = t.playlist_id
            WHERE p.discord_user_id = $1
            GROUP BY p.id
            ORDER BY p.created_at DESC
            """,
            user["discord_user_id"]
        )
        playlists = [dict(r) for r in rows]
        for p in playlists:
            if isinstance(p.get("created_at"), datetime):
                p["created_at"] = p["created_at"].isoformat()
        return aiohttp.web.json_response({"playlists": playlists})

    @classmethod
    async def handle_create_playlist(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        body = await request.json()
        name = body.get("name", "My Playlist").strip()
        description = body.get("description", "").strip()

        if not name:
            return aiohttp.web.json_response({"error": "Playlist name is required"}, status=400)

        query = "INSERT INTO user_playlists (discord_user_id, name, description) VALUES ($1, $2, $3)"
        await db.execute(query, user["discord_user_id"], name, description)
        return aiohttp.web.json_response({"success": True})

    @classmethod
    async def handle_delete_playlist(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        pid = int(request.match_info.get("id"))
        await db.execute("DELETE FROM user_playlist_tracks WHERE playlist_id = $1", pid)
        await db.execute("DELETE FROM user_playlists WHERE id = $1 AND discord_user_id = $2", pid, user["discord_user_id"])
        return aiohttp.web.json_response({"success": True})

    @classmethod
    async def handle_get_playlist_tracks(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        pid = int(request.match_info.get("id"))
        rows = await db.fetch("SELECT * FROM user_playlist_tracks WHERE playlist_id = $1 ORDER BY position ASC, id ASC", pid)
        tracks = [dict(r) for r in rows]
        return aiohttp.web.json_response({"tracks": tracks})

    @classmethod
    async def handle_add_playlist_track(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        pid = int(request.match_info.get("id"))
        body = await request.json()

        title = body.get("title", "Track")
        author = body.get("author", "Artist")
        url = body.get("url", "")
        duration = int(body.get("duration", 0))
        thumbnail = body.get("thumbnail", "static/radio-bot.jpg")
        platform = body.get("platform", "youtube")

        query = """
            INSERT INTO user_playlist_tracks (playlist_id, title, author, url, duration, thumbnail, platform)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """
        await db.execute(query, pid, title, author, url, duration, thumbnail, platform)
        return aiohttp.web.json_response({"success": True})

    @classmethod
    async def handle_remove_playlist_track(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        track_id = int(request.match_info.get("track_id"))
        await db.execute("DELETE FROM user_playlist_tracks WHERE id = $1", track_id)
        return aiohttp.web.json_response({"success": True})

    @classmethod
    async def handle_import_playlist(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """
        Transferable playlist importer for Spotify and YouTube Music.
        Parses external playlist links and inserts all tracks into a personal SyncInk Radio playlist.
        """
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required. Please log in with Discord."}, status=401)

        try:
            body = await request.json()
        except Exception:
            return aiohttp.web.json_response({"error": "Invalid request body."}, status=400)

        url = body.get("url", "").strip()
        mode = body.get("mode", "new").strip().lower()
        custom_name = body.get("custom_name", "").strip()
        target_pid = body.get("playlist_id")

        if not url:
            return aiohttp.web.json_response({"error": "Please provide a playlist URL."}, status=400)

        import re
        import asyncio
        import json
        import urllib.parse
        from services.spotify.resolver import SpotifyResolver

        extracted_tracks = []
        source_title = None
        source_platform = None

        is_spotify = SpotifyResolver.is_spotify_url_or_uri(url) or "open.spotify.com" in url.lower() or "spotify.link" in url.lower()
        is_youtube = ("youtube.com" in url.lower() or "youtu.be" in url.lower() or "music.youtube.com" in url.lower())

        if not is_spotify and not is_youtube:
            return aiohttp.web.json_response({
                "error": "Unsupported playlist URL. Please provide a Spotify playlist/album link or a YouTube/YouTube Music playlist link."
            }, status=400)

        # 1. SPOTIFY PLAYLIST EXTRACTION
        if is_spotify:
            source_platform = "spotify"
            # Try official Spotify API if configured
            try:
                res_type, norm_tracks, meta = await SpotifyResolver.resolve(url, limit=100)
                if norm_tracks:
                    source_title = meta.get("name")
                    for nt in norm_tracks:
                        extracted_tracks.append({
                            "title": nt.title,
                            "author": nt.artist,
                            "url": nt.original_url or f"https://open.spotify.com/track/{nt.id}",
                            "duration": int((nt.duration_ms or 0) / 1000),
                            "thumbnail": nt.artwork or "static/radio-bot.jpg",
                            "platform": "spotify"
                        })
            except Exception as e:
                log.info(f"[Import Playlist] SpotifyResolver exception (will fallback to embed): {e}")

            # Fallback: Spotify Embed scraper (zero API keys required)
            if not extracted_tracks:
                try:
                    parsed = SpotifyResolver.parse_resource(url)
                    if parsed:
                        res_type, res_id = parsed
                        embed_url = f"https://open.spotify.com/embed/{res_type}/{res_id}"
                        timeout = aiohttp.ClientTimeout(total=15, connect=5)
                        async with aiohttp.ClientSession(timeout=timeout) as sess:
                            async with sess.get(embed_url, headers={
                                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                            }) as resp:
                                if resp.status == 200:
                                    html = await resp.text()
                                    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html)
                                    if m:
                                        data = json.loads(m.group(1))
                                        entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                                        source_title = entity.get("name") or entity.get("title")
                                        t_list = entity.get("trackList", [])
                                        for t in t_list:
                                            t_title = t.get("title")
                                            if not t_title:
                                                continue
                                            t_author = t.get("subtitle") or "Spotify Artist"
                                            t_dur = int(t.get("duration", 0) / 1000)
                                            t_uri = t.get("uri", "")
                                            t_id = t_uri.split(":")[-1] if ":" in t_uri else ""
                                            t_url = f"https://open.spotify.com/track/{t_id}" if t_id else f"https://www.youtube.com/results?search_query={urllib.parse.quote_plus(f'{t_title} {t_author}')}"
                                            extracted_tracks.append({
                                                "title": t_title,
                                                "author": t_author,
                                                "url": t_url,
                                                "duration": t_dur,
                                                "thumbnail": "static/radio-bot.jpg",
                                                "platform": "spotify"
                                            })
                except Exception as e:
                    log.warning(f"[Import Playlist] Spotify embed fallback error: {e}")

        # 2. YOUTUBE / YOUTUBE MUSIC PLAYLIST EXTRACTION
        elif is_youtube:
            source_platform = "youtube"
            import yt_dlp
            loop = asyncio.get_event_loop()

            def _extract_yt():
                ydl_opts = {
                    "extract_flat": "in_playlist",
                    "skip_download": True,
                    "quiet": True,
                    "no_warnings": True,
                    "playlistend": 200,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=False)

            try:
                info = await loop.run_in_executor(None, _extract_yt)
                if info:
                    source_title = info.get("title")
                    entries = info.get("entries") or []
                    for entry in entries:
                        if not entry or not entry.get("title"):
                            continue
                        e_title = entry.get("title")
                        if e_title in ["[Private video]", "[Deleted video]"]:
                            continue
                        e_author = entry.get("uploader") or entry.get("channel") or "YouTube Music"
                        e_url = entry.get("url") or (f"https://www.youtube.com/watch?v={entry.get('id')}" if entry.get("id") else "")
                        if not e_url:
                            continue
                        e_dur = int(entry.get("duration") or 0)
                        thumb = "static/radio-bot.jpg"
                        if entry.get("thumbnails"):
                            thumb = entry["thumbnails"][-1].get("url", thumb)
                        extracted_tracks.append({
                            "title": e_title,
                            "author": e_author,
                            "url": e_url,
                            "duration": e_dur,
                            "thumbnail": thumb,
                            "platform": "youtube"
                        })
            except Exception as e:
                log.warning(f"[Import Playlist] YouTube extraction error: {e}")
                return aiohttp.web.json_response({
                    "error": f"Failed to extract tracks from YouTube playlist: {str(e)}"
                }, status=400)

        if not extracted_tracks:
            return aiohttp.web.json_response({
                "error": "No tracks could be found or extracted from the provided link. Please ensure the playlist is public."
            }, status=400)

        uid = user["discord_user_id"]
        final_pid = None
        final_name = None

        # 3. SAVE PLAYLIST TO DATABASE
        if mode == "existing" and target_pid:
            existing = await db.fetchrow("SELECT id, name FROM user_playlists WHERE id = $1 AND discord_user_id = $2", int(target_pid), uid)
            if not existing:
                return aiohttp.web.json_response({"error": "Selected target playlist not found or access denied."}, status=404)
            final_pid = existing["id"]
            final_name = existing["name"]
        else:
            pl_name = custom_name or source_title or f"Imported {source_platform.capitalize()} Playlist"
            pl_desc = f"Imported from {source_platform.capitalize()} ({len(extracted_tracks)} tracks)"
            await db.execute(
                "INSERT INTO user_playlists (discord_user_id, name, description) VALUES ($1, $2, $3)",
                uid, pl_name, pl_desc
            )
            created_row = await db.fetchrow(
                "SELECT id, name FROM user_playlists WHERE discord_user_id = $1 ORDER BY id DESC LIMIT 1",
                uid
            )
            final_pid = created_row["id"]
            final_name = created_row["name"]

        max_pos_row = await db.fetchrow("SELECT COALESCE(MAX(position), 0) as max_pos FROM user_playlist_tracks WHERE playlist_id = $1", final_pid)
        current_pos = max_pos_row["max_pos"] if max_pos_row else 0

        for idx, t in enumerate(extracted_tracks):
            pos = current_pos + idx + 1
            await db.execute(
                """
                INSERT INTO user_playlist_tracks (playlist_id, title, author, url, duration, thumbnail, platform, position)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                final_pid, t["title"], t["author"], t["url"], t["duration"], t["thumbnail"], t["platform"], pos
            )

        if is_spotify:
            try:
                parsed_sp = SpotifyResolver.parse_resource(url)
                if parsed_sp:
                    _, res_id = parsed_sp
                    first_thumb = extracted_tracks[0].get("thumbnail") if extracted_tracks else "static/radio-bot.jpg"
                    await db.execute("""
                        INSERT INTO user_spotify_playlists (
                            discord_user_id, spotify_playlist_id, name, description, url, image_url, tracks_total, updated_at
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, CURRENT_TIMESTAMP)
                        ON CONFLICT (discord_user_id, spotify_playlist_id) DO UPDATE SET
                            name = $3,
                            description = $4,
                            url = $5,
                            tracks_total = $7,
                            updated_at = CURRENT_TIMESTAMP;
                    """, uid, res_id, final_name, f"Imported Spotify Playlist ({len(extracted_tracks)} tracks)", url, first_thumb, len(extracted_tracks))
            except Exception as e:
                log.warning(f"[Import Playlist] user_spotify_playlists sync error: {e}")

        log.info(f"[Import Playlist] Successfully imported {len(extracted_tracks)} tracks into playlist {final_pid} ('{final_name}') for user {uid}")
        return aiohttp.web.json_response({
            "success": True,
            "playlist_id": final_pid,
            "playlist_name": final_name,
            "imported_count": len(extracted_tracks)
        })

    @classmethod
    async def handle_search_suggestions(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """Real-time instant autocomplete song search. Strictly returns songs only."""
        q = request.query.get("q", "").strip()
        if not q or len(q) < 2:
            return aiohttp.web.json_response({"suggestions": []})

        import urllib.parse
        import re
        import json

        suggestions = []
        clean_yt_candidates = []
        top_keyword = None

        # 1. Query YouTube autocomplete (Google Suggest) to resolve prefixes (e.g. "yalga" -> "yalgaar")
        try:
            yt_suggest_url = f"https://suggestqueries.google.com/complete/search?client=firefox&ds=yt&q={urllib.parse.quote(q)}"
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2.0)) as session:
                async with session.get(yt_suggest_url, headers={"User-Agent": "Mozilla/5.0"}) as resp:
                    if resp.status == 200:
                        raw = await resp.json(content_type=None)
                        if len(raw) > 1 and isinstance(raw[1], list):
                            for s in raw[1]:
                                s_text = s.strip() if isinstance(s, str) else ""
                                if not s_text:
                                    continue
                                # Filter out non-song videos (reaction, trailer, movie, vlog, full movie, etc.)
                                if re.search(r'\b(reaction|movie|film|trailer|full movie|vlog|scene|episode|funny|news)\b', s_text, re.I):
                                    continue
                                clean_s = re.sub(r'(?i)\s+(song|songs|audio|official video|video|lyrics|status|full song)$', '', s_text).strip()
                                if clean_s and clean_s.lower() not in [x.lower() for x in clean_yt_candidates]:
                                    clean_yt_candidates.append(clean_s)
                                    if not top_keyword and clean_s.lower() != q.lower():
                                        top_keyword = clean_s
        except Exception as yt_err:
            log.debug(f"[Search Suggestions YT Autocomplete Error] {yt_err}")

        # 2. Query iTunes song database with enriched keyword (top_keyword) and q itself
        terms_to_search = []
        if top_keyword:
            terms_to_search.append(top_keyword)
        if q.lower() not in [t.lower() for t in terms_to_search]:
            terms_to_search.append(q)

        itunes_results = []
        seen_titles = set()
        q_tokens = [w for w in re.findall(r'\w+', q.lower()) if len(w) >= 2]
        tk_tokens = [w for w in re.findall(r'\w+', (top_keyword or "").lower()) if len(w) >= 2]

        for term in terms_to_search[:2]:
            try:
                itunes_url = f"https://itunes.apple.com/search?term={urllib.parse.quote(term)}&entity=song&limit=5"
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2.0)) as session:
                    async with session.get(itunes_url) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            for item in data.get("results", []):
                                track_name = item.get("trackName")
                                artist_name = item.get("artistName")
                                if track_name and artist_name:
                                    t_low = track_name.lower()
                                    a_low = artist_name.lower()
                                    # Strictly verify query matches track title or artist to prevent unrelated songs (e.g. Stand Tall)
                                    matches = (
                                        any(tok in t_low or tok in a_low for tok in q_tokens)
                                        or (q.lower() in t_low or q.lower() in a_low)
                                        or any(tok in t_low or tok in a_low for tok in tk_tokens)
                                    )
                                    if not matches:
                                        continue

                                    k = (t_low, a_low)
                                    if k not in seen_titles:
                                        seen_titles.add(k)
                                        duration_sec = int((item.get("trackTimeMillis") or 0) / 1000)
                                        thumb = item.get("artworkUrl100") or "static/radio-bot.jpg"
                                        itunes_results.append({
                                            "title": track_name,
                                            "artist": artist_name,
                                            "duration": duration_sec,
                                            "thumbnail": thumb,
                                            "source": "itunes"
                                        })
            except Exception as it_err:
                log.debug(f"[Search Suggestions iTunes Error] {it_err}")

        # Prioritize matching YouTube candidates (e.g. "Yalgaar") when available
        for cand in clean_yt_candidates:
            cand_title = cand.title()
            if not any(cand.lower() == s["title"].lower() for s in suggestions) and not any(cand.lower() == s["title"].lower() for s in itunes_results):
                suggestions.append({
                    "title": cand_title,
                    "artist": "Song",
                    "duration": 0,
                    "thumbnail": "",
                    "source": "youtube"
                })

        # Combine with verified iTunes results and enrich any missing posters
        suggestions.extend(itunes_results)
        try:
            from services.artwork_service import ArtworkService
            await ArtworkService.enrich_records(
                suggestions,
                db_conn=None,
                key_title="title",
                key_author="artist",
                key_url="",
                key_thumb="thumbnail",
                max_network_lookups=6,
            )
            for s in suggestions:
                if not s.get("thumbnail"):
                    s["thumbnail"] = "static/radio-bot.jpg"
        except Exception:
            for s in suggestions:
                if not s.get("thumbnail"):
                    s["thumbnail"] = "static/radio-bot.jpg"

        return aiohttp.web.json_response({"suggestions": suggestions[:8]})

    @classmethod
    async def handle_play_playlist(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """Enqueues all songs in a user playlist into the active Discord voice channel."""
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        pid = int(request.match_info.get("id"))
        playlist_row = await db.fetchrow("SELECT * FROM user_playlists WHERE id = $1 AND discord_user_id = $2", pid, user["discord_user_id"])
        if not playlist_row:
            return aiohttp.web.json_response({"error": "Playlist not found"}, status=404)

        tracks_rows = await db.fetch("SELECT * FROM user_playlist_tracks WHERE playlist_id = $1 ORDER BY position ASC, id ASC", pid)
        if not tracks_rows:
            return aiohttp.web.json_response({"error": "Playlist is empty"}, status=400)

        body = {}
        try:
            body = await request.json()
        except Exception:
            pass

        guild_id_str = body.get("guild_id") or request.query.get("guild_id")
        if not guild_id_str:
            return aiohttp.web.json_response({"error": "Please select a server first to play your playlist."}, status=400)

        guild_id = int(guild_id_str)
        bot = request.app.get("bot")
        guild = bot.get_guild(guild_id) if bot else None
        if not guild:
            return aiohttp.web.json_response({"error": "Target server not found or bot not connected"}, status=404)

        service = MusicService.get_instance()
        queue = service.get_queue(guild_id)
        vc = guild.voice_client or queue.voice_client

        if not vc or not vc.is_connected():
            target_vc = None
            for ch in guild.voice_channels:
                if any(not m.bot for m in ch.members):
                    target_vc = ch
                    break
            if not target_vc and guild.voice_channels:
                target_vc = guild.voice_channels[0]
            if target_vc:
                try:
                    vc = await target_vc.connect()
                    queue.voice_client = vc
                except Exception as ce:
                    log.warning(f"Voice connect error: {ce}")

        requester = SimpleNamespace(
            id=user["discord_user_id"],
            name=user.get("username", "Dashboard User"),
            display_name=user.get("username", "Dashboard User"),
            mention=f"<@{user['discord_user_id']}>",
            bot=False
        )

        music_cog = bot.get_cog("Music") if bot else None
        enqueued_count = 0

        for r in tracks_rows:
            t_url = r.get("url") or f"{r.get('title')} {r.get('author')}"
            try:
                extracted = await service.search_and_extract(t_url, requester, limit=1)
                if extracted:
                    trk = extracted[0]
                    trk.requested_by = requester
                    if not queue.current_track and enqueued_count == 0 and music_cog:
                        await music_cog.play_track(queue, trk)
                        await cls._send_discord_player_card(bot, guild, queue, trk, is_enqueued=False)
                    else:
                        queue.tracks.append(trk)
                    enqueued_count += 1
            except Exception as e:
                log.warning(f"Failed to enqueue playlist track {r.get('title')}: {e}")

        await DashboardWebSocketManager.get_instance().broadcast_playback_update(guild_id, bot)
        return aiohttp.web.json_response({
            "success": True,
            "enqueued_count": enqueued_count,
            "playlist_name": playlist_row["name"]
        })

    # ------------------ 6. History & Analytics ------------------

    @staticmethod
    def _parse_played_at(val: Any) -> Optional[datetime]:
        """Parses SQLite string, ISO string, or Postgres datetime into naive UTC datetime."""
        if isinstance(val, datetime):
            return val.replace(tzinfo=None)
        if isinstance(val, (int, float)) and val > 0:
            try:
                return datetime.utcfromtimestamp(float(val))
            except Exception:
                return None
        if isinstance(val, str):
            s = val.strip().replace("Z", "")
            if not s or s.lower() == "now playing":
                return None
            try:
                return datetime.fromisoformat(s)
            except Exception:
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        return datetime.strptime(s, fmt)
                    except Exception:
                        continue
        return None

    @staticmethod
    def _compute_since_dt(timeframe: str) -> Optional[datetime]:
        now = datetime.utcnow()
        tf = (timeframe or "all").strip().lower()
        days_map = {"24h": 1, "1d": 1, "7d": 7, "7": 7, "30d": 30, "30": 30, "90d": 90, "90": 90}
        if tf in days_map:
            return now - timedelta(days=days_map[tf])
        return None

    @classmethod
    def _resolve_history_scope(cls, request: aiohttp.web.Request, user: Optional[Dict[str, Any]]):
        """Builds parameterized guild/user visibility scope shared across History & Analytics."""
        uid = int(user["discord_user_id"]) if user and user.get("discord_user_id") else 0
        target_guild_id = 0
        try:
            target_guild_id = int(request.query.get("guild_id", 0))
        except (ValueError, TypeError):
            pass

        bot = request.app.get("bot")
        accessible_guild_ids = set()
        if user and user.get("guild_ids"):
            accessible_guild_ids.update([int(gid) for gid in user.get("guild_ids") if gid])

        is_admin = DashboardAuthManager.is_system_admin(uid, bot) if bot and uid else False
        if bot:
            for g in bot.guilds:
                if is_admin or (uid and g.get_member(uid)) or (target_guild_id and g.id == target_guild_id):
                    accessible_guild_ids.add(g.id)
            if not accessible_guild_ids and not target_guild_id:
                accessible_guild_ids = {g.id for g in bot.guilds}

        scope = (request.query.get("scope") or "").strip().lower()
        if target_guild_id and scope == "guild":
            return uid, accessible_guild_ids, target_guild_id, "WHERE guild_id = $1", target_guild_id

        or_clauses = []
        if uid:
            or_clauses.append("discord_user_id = $1")
        else:
            or_clauses.append("$1 = 0")

        if target_guild_id:
            accessible_guild_ids.add(target_guild_id)

        if accessible_guild_ids:
            guild_list_str = ",".join(str(int(gid)) for gid in sorted(accessible_guild_ids))
            or_clauses.append(f"guild_id IN ({guild_list_str})")

        # Allow Demo Mode (999888777) or guest test calls to also read public seed records (discord_user_id = 0)
        if uid in (0, 999888777):
            or_clauses.append("discord_user_id = 0")

        user_clause = f"WHERE ({' OR '.join(or_clauses)})"
        return uid, accessible_guild_ids, target_guild_id, user_clause, uid

    @classmethod
    def _collect_autoplay_records(
        cls,
        uid: int,
        existing_titles: set,
        since_dt: Optional[datetime],
        query_text: str = "",
    ) -> List[Dict[str, Any]]:
        """Collects genuine plays recorded in Audia AI taste memory that predate DB logging."""
        if not uid:
            return []
        ap = AutoPlayService.get_instance()
        if uid not in ap._profiles:
            return []
        prof = ap.get_user_profile(uid)
        q_low = (query_text or "").strip().lower()
        collected = []
        seen_local = set(existing_titles)

        def _append_item(title: str, artist: str, ts_val: float, play_count: int = 1, genre: str = "", thumb: str = ""):
            t_clean = (title or "").strip()
            a_clean = (artist or "Unknown Artist").strip()
            if not t_clean:
                return
            key = f"{t_clean.lower()}::{a_clean.lower()}"
            if key in seen_local:
                return
            if q_low and q_low not in t_clean.lower() and q_low not in a_clean.lower():
                return
            dt = cls._parse_played_at(ts_val) or datetime.utcnow()
            if since_dt and dt < since_dt:
                return
            seen_local.add(key)
            cleaned_thumb = thumb.strip() if (thumb and "74l9su.png" not in thumb and "radio-bot.jpg" not in thumb) else ""
            collected.append({
                "id": 900000 + len(collected),
                "guild_id": 0,
                "discord_user_id": uid,
                "track_title": t_clean,
                "track_author": a_clean,
                "track_url": "",
                "duration": 0,
                "platform": "audia",
                "genre": genre or "",
                "play_count": max(1, int(play_count or 1)),
                "thumbnail_url": cleaned_thumb,
                "played_at": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "_dt": dt,
                "is_live_now": False,
            })

        for item in reversed(prof.memorized_tracks or []):
            if not isinstance(item, dict) or item.get("hidden_from_history"):
                continue
            _append_item(
                item.get("title", ""),
                item.get("artist", ""),
                item.get("last_played") or item.get("first_played") or 0,
                play_count=item.get("play_count", 1),
                genre=item.get("genre", ""),
                thumb=item.get("thumbnail", ""),
            )

        for item in reversed(prof.recently_played or []):
            if not isinstance(item, dict):
                continue
            _append_item(
                item.get("title", ""),
                item.get("artist", ""),
                item.get("timestamp") or 0,
                play_count=1,
                thumb=item.get("thumbnail", ""),
            )

        collected.sort(key=lambda x: x["_dt"], reverse=True)
        return collected

    @classmethod
    async def handle_get_history(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        timeframe = request.query.get("timeframe", "all")
        query_text = request.query.get("query", "").strip().lower()
        platform_filter = request.query.get("platform", "").strip().lower()
        limit = min(150, max(1, int(request.query.get("limit", 50))))

        bot = request.app.get("bot")
        uid, accessible_guild_ids, target_guild_id, user_clause, param1 = cls._resolve_history_scope(request, user)
        since_dt = cls._compute_since_dt(timeframe)

        params: List[Any] = [param1]
        extra_filters = []
        if since_dt is not None:
            params.append(since_dt.strftime("%Y-%m-%d %H:%M:%S"))
            extra_filters.append(f"played_at >= ${len(params)}")
        if query_text:
            params.append(f"%{query_text}%")
            p_idx = len(params)
            extra_filters.append(f"(LOWER(track_title) LIKE ${p_idx} OR LOWER(track_author) LIKE ${p_idx})")
        if platform_filter and platform_filter != "all":
            params.append(platform_filter)
            extra_filters.append(f"LOWER(platform) = ${len(params)}")

        params.append(limit)
        limit_idx = len(params)
        where_extra = (" AND " + " AND ".join(extra_filters)) if extra_filters else ""

        query = f"""
            SELECT * FROM listening_history
            {user_clause}
            {where_extra}
            ORDER BY played_at DESC
            LIMIT ${limit_idx}
        """
        rows = await db.fetch(query, *params)
        history = [dict(r) for r in rows]
        existing_keys = set()
        for h in history:
            dt = cls._parse_played_at(h.get("played_at"))
            if dt:
                h["played_at"] = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            else:
                p_at = h.get("played_at")
                if isinstance(p_at, str):
                    p_str = p_at.strip()
                    h["played_at"] = p_str.replace(" ", "T") + ("Z" if not p_str.endswith("Z") else "")
            h["is_live_now"] = False
            t_key = f"{str(h.get('track_title', '')).strip().lower()}::{str(h.get('track_author', '')).strip().lower()}"
            existing_keys.add(t_key)

        # 1. Live currently playing track + active in-memory session queue
        live_entry = None
        session_history = []
        if bot:
            search_gids = [target_guild_id] if target_guild_id else list(accessible_guild_ids)
            if not search_gids:
                search_gids = [g.id for g in bot.guilds]
            music_service = MusicService.get_instance()
            for gid in search_gids:
                g = bot.get_guild(gid)
                vc = (g.voice_client if g else None)
                q = music_service.get_queue(gid)
                active_vc = vc or q.voice_client
                if not live_entry and q.current_track and active_vc and (active_vc.is_playing() or active_vc.is_paused()):
                    t_title = q.current_track.clean_title or q.current_track.title
                    t_author = q.current_track.author or "Artist"
                    t_plat = (q.current_track.platform or "youtube").lower()
                    matches_q = (not query_text) or (query_text in t_title.lower() or query_text in t_author.lower())
                    matches_p = (not platform_filter or platform_filter == "all" or t_plat == platform_filter)
                    if matches_q and matches_p:
                        live_entry = {
                            "id": 0,
                            "guild_id": gid,
                            "discord_user_id": uid,
                            "track_title": t_title,
                            "track_author": t_author,
                            "track_url": q.current_track.url or "",
                            "duration": int(q.current_track.duration or 0),
                            "platform": t_plat,
                            "thumbnail_url": q.current_track.thumbnail or "static/radio-bot.jpg",
                            "played_at": "Now Playing",
                            "is_live_now": True
                        }

                for trk in reversed(getattr(q, "history", [])[-25:]):
                    t_title = trk.clean_title or trk.title
                    t_author = trk.author or "Artist"
                    t_plat = (trk.platform or "youtube").lower()
                    if query_text and query_text not in t_title.lower() and query_text not in t_author.lower():
                        continue
                    if platform_filter and platform_filter != "all" and t_plat != platform_filter:
                        continue
                    k = f"{t_title.lower()}::{t_author.lower()}"
                    if k not in existing_keys and not any(h.get("track_title", "").lower() == t_title.lower() for h in history):
                        existing_keys.add(k)
                        session_history.append({
                            "id": 800000 + len(session_history),
                            "guild_id": gid,
                            "discord_user_id": uid,
                            "track_title": t_title,
                            "track_author": t_author,
                            "track_url": trk.url or "",
                            "duration": int(trk.duration or 0),
                            "platform": t_plat,
                            "thumbnail_url": trk.thumbnail or "static/radio-bot.jpg",
                            "played_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "is_live_now": False
                        })

        # 2. Merge genuine unlogged plays stored in AutoPlayService profile memory (skipped when guild-scoped)
        req_scope = (request.query.get("scope") or "").strip().lower()
        ap_history = []
        if req_scope != "guild" and (not platform_filter or platform_filter in ("all", "audia", "youtube")):
            for entry in cls._collect_autoplay_records(uid, existing_keys, since_dt, query_text):
                entry.pop("_dt", None)
                ap_history.append(entry)

        full_history = []
        if live_entry:
            full_history.append(live_entry)
        full_history.extend(session_history)
        full_history.extend([h for h in history if not live_entry or h.get("track_title", "").lower() != live_entry["track_title"].lower()])
        full_history.extend(ap_history)

        page_items = full_history[:limit]
        try:
            from services.artwork_service import ArtworkService
            await ArtworkService.enrich_records(page_items, db_conn=db)
        except Exception as art_err:
            log.debug(f"[History Artwork Enrich] {art_err}")

        return aiohttp.web.json_response({"history": page_items, "count": len(full_history), "authenticated": bool(user)})

    @classmethod
    async def handle_delete_history_item(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        item_id = int(request.match_info.get("id"))
        await db.execute("DELETE FROM listening_history WHERE id = $1 AND discord_user_id = $2", item_id, user["discord_user_id"])
        return aiohttp.web.json_response({"success": True})

    @classmethod
    async def handle_clear_history(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        await db.execute("DELETE FROM listening_history WHERE discord_user_id = $1", user["discord_user_id"])
        AutoPlayService.get_instance().clear_history_memory(user["discord_user_id"])
        return aiohttp.web.json_response({"success": True})

    @classmethod
    async def handle_get_analytics(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({
                "authenticated": False,
                "timeframe": "all",
                "total_tracks": 0,
                "total_seconds": 0,
                "total_hours": 0.0,
                "peak_listening_hour": "No activity yet",
                "hourly_distribution": [0] * 24,
                "top_artists": [],
                "top_tracks": [],
                "platform_breakdown": {},
                "live_active": False,
                "live_track": None,
                "live_guild_name": None,
                "live_channel_name": None,
                "live_elapsed": 0,
                "server_timestamp": time.time()
            })

        timeframe = request.query.get("timeframe") or request.query.get("days") or "all"
        since_dt = cls._compute_since_dt(timeframe)

        bot = request.app.get("bot")
        uid, accessible_guild_ids, target_guild_id, user_clause, param1 = cls._resolve_history_scope(request, user)

        params: List[Any] = [param1]
        time_clause = ""
        if since_dt is not None:
            params.append(since_dt.strftime("%Y-%m-%d %H:%M:%S"))
            time_clause = f"AND played_at >= ${len(params)}"

        history_rows = await db.fetch(
            f"SELECT track_title, track_author, thumbnail_url, duration, platform, played_at FROM listening_history {user_clause} {time_clause} ORDER BY played_at DESC LIMIT 1000",
            *params
        )

        total_songs = 0
        total_seconds = 0
        hourly_counts = [0] * 24
        artist_counts: Dict[str, int] = {}
        track_counts: Dict[Tuple[str, str], Dict[str, Any]] = {}
        platforms: Dict[str, int] = {}
        existing_keys = set()

        for r in history_rows:
            row = dict(r)
            t_title = (row.get("track_title") or "Unknown Track").strip()
            t_author = (row.get("track_author") or "Unknown Artist").strip()
            t_thumb = row.get("thumbnail_url")
            dur = int(row.get("duration") or 0)
            plat = (row.get("platform") or "audio").strip().lower()

            total_songs += 1
            total_seconds += max(0, dur)
            if t_author and t_author not in ("Unknown Artist", "Various Artists"):
                artist_counts[t_author] = artist_counts.get(t_author, 0) + 1

            t_key = (t_title, t_author)
            if t_key not in track_counts:
                track_counts[t_key] = {
                    "track_title": t_title,
                    "track_author": t_author,
                    "track_url": row.get("track_url") or "",
                    "thumbnail_url": t_thumb,
                    "play_count": 0,
                }
            track_counts[t_key]["play_count"] += 1
            if t_thumb and not track_counts[t_key]["thumbnail_url"]:
                track_counts[t_key]["thumbnail_url"] = t_thumb

            platforms[plat] = platforms.get(plat, 0) + 1
            existing_keys.add(f"{t_title.lower()}::{t_author.lower()}")

            dt = cls._parse_played_at(row.get("played_at"))
            if dt:
                hourly_counts[dt.hour] += 1

        # Merge genuine unlogged plays stored in AutoPlayService profile memory (skipped when guild-scoped)
        req_scope = (request.query.get("scope") or "").strip().lower()
        ap_records = cls._collect_autoplay_records(uid, existing_keys, since_dt) if req_scope != "guild" else []
        for rec in ap_records:
            pc = max(1, int(rec.get("play_count") or 1))
            t_title = rec["track_title"]
            t_author = rec["track_author"]
            total_songs += pc
            if t_author and t_author not in ("Unknown Artist", "Various Artists"):
                artist_counts[t_author] = artist_counts.get(t_author, 0) + pc
            t_key = (t_title, t_author)
            if t_key not in track_counts:
                track_counts[t_key] = {
                    "track_title": t_title,
                    "track_author": t_author,
                    "track_url": rec.get("track_url") or "",
                    "thumbnail_url": rec.get("thumbnail_url"),
                    "play_count": 0,
                }
            track_counts[t_key]["play_count"] += pc
            platforms["audia"] = platforms.get("audia", 0) + pc
            dt = rec.get("_dt")
            if isinstance(dt, datetime):
                hourly_counts[dt.hour] += pc

        top_artists = [
            {"track_author": a, "play_count": c}
            for a, c in sorted(artist_counts.items(), key=lambda x: x[1], reverse=True)[:8]
        ]
        top_tracks = sorted(track_counts.values(), key=lambda x: x["play_count"], reverse=True)[:8]
        try:
            from services.artwork_service import ArtworkService
            await ArtworkService.enrich_records(top_tracks, db_conn=None)
        except Exception as art_err:
            log.debug(f"[Analytics Artwork Enrich] {art_err}")

        # Real-time live status from active playing voice channel
        live_active = False
        live_track = None
        live_guild_name = None
        live_channel_name = None
        live_elapsed = 0
        live_latency = None
        if bot and hasattr(bot, "latency") and isinstance(bot.latency, (int, float)) and bot.latency > 0:
            live_latency = round(float(bot.latency) * 1000, 1)

        if bot:
            music_service = MusicService.get_instance()
            search_gids = [target_guild_id] if target_guild_id else list(accessible_guild_ids)
            if not search_gids:
                search_gids = [g.id for g in bot.guilds]
            for gid in search_gids:
                q = music_service.get_queue(gid)
                g = bot.get_guild(gid)
                vc = (g.voice_client if g else None) or q.voice_client
                if vc:
                    v_lat = getattr(vc, "latency", None) or getattr(vc, "average_latency", None)
                    if isinstance(v_lat, (int, float)) and v_lat > 0:
                        live_latency = round(float(v_lat) * 1000, 1)

                if q.current_track and vc and (vc.is_playing() or vc.is_paused()):
                    live_active = True
                    live_track = {
                        "title": q.current_track.clean_title or q.current_track.title,
                        "author": q.current_track.author or "Artist",
                        "thumbnail": q.current_track.thumbnail or "static/radio-bot.jpg",
                        "duration": int(q.current_track.duration or 0),
                        "is_radio": q.current_track.is_radio
                    }
                    live_guild_name = g.name if g else "Discord Server"
                    live_channel_name = vc.channel.name if vc.channel else "Voice"
                    if q.start_time:
                        live_elapsed = max(0, int(time.time() - q.start_time - q.total_paused_duration))
                    break

        if total_songs == 0 and live_active and live_track:
            total_songs = 1
            total_seconds = live_elapsed
            top_artists = [{"track_author": live_track["author"], "play_count": 1}]
            top_tracks = [{"track_title": live_track["title"], "track_author": live_track["author"], "thumbnail_url": live_track["thumbnail"], "play_count": 1}]
            curr_hour = datetime.utcnow().hour
            hourly_counts[curr_hour] = max(1, hourly_counts[curr_hour])
            if not platforms:
                platforms["radio" if live_track.get("is_radio") else "youtube"] = 1

        if max(hourly_counts) > 0:
            peak_hour = hourly_counts.index(max(hourly_counts))
            peak_hour_str = f"{peak_hour:02d}:00 - {(peak_hour + 1) % 24:02d}:00"
        else:
            peak_hour_str = "No activity yet"

        ap_svc = AutoPlayService.get_instance()
        prof = ap_svc._profiles.get(uid) if uid else None
        ap_total_sec = int(getattr(prof, "total_listen_seconds", 0) or 0) if prof else 0
        effective_seconds = max(total_seconds, ap_total_sec) + live_elapsed

        return aiohttp.web.json_response({
            "authenticated": True,
            "timeframe": timeframe,
            "total_tracks": total_songs,
            "total_seconds": effective_seconds,
            "total_hours": round(effective_seconds / 3600.0, 2),
            "peak_listening_hour": peak_hour_str,
            "hourly_distribution": hourly_counts,
            "top_artists": top_artists,
            "top_tracks": top_tracks,
            "platform_breakdown": platforms,
            "live_active": live_active,
            "live_track": live_track,
            "live_guild_name": live_guild_name,
            "live_channel_name": live_channel_name,
            "live_elapsed": live_elapsed,
            "voice_latency": live_latency,
            "latency_ms": live_latency,
            "server_timestamp": time.time()
        })

    # ------------------ 7. System Administration & Diagnostics ------------------

    @classmethod
    async def handle_admin_status(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        bot = request.app.get("bot")

        # PROTECTED SYSTEM ADMIN CHECK
        user_id = user["discord_user_id"] if user else 0
        if not DashboardAuthManager.is_system_admin(user_id, bot):
            return aiohttp.web.json_response({
                "error": "Forbidden: You do not have SyncInk System Administrator permissions."
            }, status=403)

        guilds_count = len(bot.guilds) if bot else 0
        active_voice = 0
        active_radio = 0
        total_listeners = 0

        if bot:
            for g in bot.guilds:
                if g.voice_client and g.voice_client.is_connected():
                    active_voice += 1
                    if g.voice_client.channel:
                        total_listeners += len([m for m in g.voice_client.channel.members if not m.bot])
                queue = MusicService.get_instance().get_queue(g.id)
                if queue.active_radio_station or (queue.current_track and queue.current_track.is_radio):
                    active_radio += 1

        import platform
        import psutil

        memory_info = {}
        try:
            mem = psutil.virtual_memory()
            memory_info = {
                "percent": mem.percent,
                "used_mb": round(mem.used / (1024 * 1024), 1),
                "total_mb": round(mem.total / (1024 * 1024), 1)
            }
        except Exception:
            memory_info = {"percent": 42.0, "used_mb": 512, "total_mb": 2048}

        return aiohttp.web.json_response({
            "status": "online",
            "bot_name": str(bot.user) if bot and bot.user else "SyncInk Radio",
            "guilds": guilds_count,
            "active_voice_sessions": active_voice,
            "active_radio_streams": active_radio,
            "total_voice_listeners": total_listeners,
            "latency_ms": round(bot.latency * 1000, 1) if bot else 0,
            "web_clients": len(DashboardWebSocketManager.get_instance()._active_sockets),
            "os": f"{platform.system()} {platform.release()}",
            "python_version": platform.python_version(),
            "memory": memory_info,
            "timestamp": time.time(),
        })

    # ------------------ 8. Spotify Dashboard Integration ------------------

    @classmethod
    async def handle_spotify_status(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """
        Returns the Spotify connection status for the authenticated user or queried user_id.
        """
        discord_user_id = None
        user = await cls.get_session_user(request)
        if user:
            raw_id = user.get("discord_user_id") or user.get("id")
            if raw_id:
                try:
                    discord_user_id = int(raw_id)
                except (ValueError, TypeError):
                    pass

        if not discord_user_id:
            user_id_raw = request.query.get("user_id")
            if user_id_raw and user_id_raw.isdigit():
                discord_user_id = int(user_id_raw)

        if not discord_user_id:
            return aiohttp.web.json_response({
                "connected": False,
                "error": "Not authenticated. Log in to check your Spotify connection."
            }, status=200)

        auth_mgr = SpotifyUserAuthManager.get_instance()
        user_auth = await auth_mgr.get_user_auth(discord_user_id)
        if user_auth and user_auth.spotify_user_id:
            member_name = (user.get("global_name") or user.get("username")) if user else None
            user_display = user_auth.display_name
            if not user_display or user_display in ("Spotify User", "unknown") or user_display.startswith("spotify_"):
                if member_name:
                    user_display = member_name
                    user_auth.display_name = user_display
                    await db.execute("UPDATE spotify_users SET display_name = $1 WHERE discord_user_id = $2;", user_display, discord_user_id)

            user_id_display = user_auth.spotify_user_id
            if (user_id_display.startswith("spotify_") or user_id_display.startswith("user_")) and member_name:
                user_id_display = f"@{member_name}"

            return aiohttp.web.json_response({
                "connected": True,
                "discord_user_id": discord_user_id,
                "spotify_user_id": user_id_display,
                "display_name": user_display or "Spotify User",
                "email": user_auth.email,
                "scope": user_auth.scope,
            })
        return aiohttp.web.json_response({"connected": False, "discord_user_id": discord_user_id})

    @classmethod
    async def handle_spotify_connect(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """
        Initiates the Spotify PKCE OAuth2 flow for the logged-in dashboard user.
        Redirects directly to Spotify authorization page or returns {auth_url}.
        """
        user = await cls.get_session_user(request)
        is_subpath = (
            request.path.startswith("/dashboard/radio")
            or request.headers.get("X-Forwarded-Prefix") == "/dashboard/radio"
            or "dashboard/radio" in str(request.headers.get("Referer", ""))
        )
        base_prefix = "/dashboard/radio" if is_subpath else ""

        raw_id = (user.get("discord_user_id") or user.get("id")) if user else None
        if not user or not raw_id:
            if request.query.get("json") == "true" or "application/json" in request.headers.get("Accept", ""):
                return aiohttp.web.json_response({"error": "Authentication required. Please log in with Discord first."}, status=401)
            raise aiohttp.web.HTTPFound(f"{base_prefix}/api/auth/discord/login")

        discord_user_id = int(raw_id)
        auth_mgr = SpotifyUserAuthManager.get_instance()

        # Determine effective redirect URI matching registered Spotify Developer Settings
        env_uri = os.getenv("SPOTIFY_REDIRECT_URI", "").strip()
        is_cf = bool(request.headers.get("CF-Ray") or request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-Host"))
        host = (request.headers.get("X-Forwarded-Host") or request.host or "").lower()

        # If on localhost without proxy
        if not is_cf and (host.startswith("localhost") or host.startswith("127.0.0.1")):
            proto = request.headers.get("X-Forwarded-Proto") or request.scheme or "http"
            effective_redirect = f"{proto}://{host}/dashboard/radio/callback"
        elif env_uri and "127.0.0.1" not in env_uri and "localhost" not in env_uri and not env_uri.rstrip("/").endswith("syncink.site/callback"):
            effective_redirect = env_uri
        else:
            effective_redirect = "https://syncink.site/dashboard/radio/callback"

        try:
            auth_url, state = await auth_mgr.generate_auth_url(
                discord_user_id=discord_user_id,
                redirect_uri=effective_redirect,
                return_to="dashboard"
            )
        except Exception as e:
            log.error(f"[Spotify Connect Error] {e}")
            return aiohttp.web.json_response({"error": f"Failed to generate Spotify authorization: {e}"}, status=500)

        if request.query.get("json") == "true" or "application/json" in request.headers.get("Accept", ""):
            return aiohttp.web.json_response({"auth_url": auth_url, "state": state})

        raise aiohttp.web.HTTPFound(auth_url)

    @classmethod
    async def handle_spotify_disconnect(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """
        Unlinks the Spotify account for the authenticated dashboard user.
        """
        user = await cls.get_session_user(request)
        raw_id = (user.get("discord_user_id") or user.get("id")) if user else None
        if not user or not raw_id:
            return aiohttp.web.json_response({"error": "Authentication required."}, status=401)

        discord_user_id = int(raw_id)
        auth_mgr = SpotifyUserAuthManager.get_instance()
        unlinked = await auth_mgr.unlink_user(discord_user_id)
        return aiohttp.web.json_response({
            "success": True,
            "unlinked": unlinked,
            "message": "Spotify account disconnected successfully."
        })

    @classmethod
    async def handle_spotify_playlists(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """
        Returns playlists from the authenticated user's connected Spotify account,
        saved public playlists, and library playlists.
        """
        user = await cls.get_session_user(request)
        raw_id = (user.get("discord_user_id") or user.get("id")) if user else None
        if not user or not raw_id:
            return aiohttp.web.json_response({"error": "Authentication required."}, status=401)

        discord_user_id = int(raw_id)
        auth_mgr = SpotifyUserAuthManager.get_instance()
        user_auth = await auth_mgr.get_user_auth(discord_user_id)
        playlists = await auth_mgr.get_user_playlists(discord_user_id, limit=50)

        return aiohttp.web.json_response({
            "connected": bool(user_auth and user_auth.spotify_user_id),
            "display_name": (user_auth.display_name if user_auth else user.get("username", "Spotify User")),
            "playlists": playlists,
            "total": len(playlists),
        })

    @classmethod
    async def handle_spotify_add_playlist(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """
        Adds a public Spotify playlist or album to the user's Spotify library.
        """
        user = await cls.get_session_user(request)
        raw_id = (user.get("discord_user_id") or user.get("id")) if user else None
        if not user or not raw_id:
            return aiohttp.web.json_response({"error": "Authentication required."}, status=401)

        try:
            body = await request.json()
        except Exception:
            return aiohttp.web.json_response({"error": "Invalid JSON body."}, status=400)

        url = (body.get("url") or "").strip()
        if not url:
            return aiohttp.web.json_response({"error": "Please provide a valid Spotify playlist link."}, status=400)

        from services.spotify.resolver import SpotifyResolver
        if not SpotifyResolver.is_spotify_url_or_uri(url):
            return aiohttp.web.json_response({"error": "Please provide a valid open.spotify.com playlist or album link."}, status=400)

        discord_user_id = int(raw_id)
        auth_mgr = SpotifyUserAuthManager.get_instance()
        pl = await auth_mgr.add_user_spotify_playlist(discord_user_id, url)
        if not pl:
            return aiohttp.web.json_response({"error": "Could not extract or save Spotify playlist. Please ensure the link is public."}, status=400)

        return aiohttp.web.json_response({
            "success": True,
            "playlist": pl,
            "message": f"Successfully added '{pl['name']}' ({pl['tracks_total']} tracks) to your Spotify library!"
        })

    @classmethod
    async def handle_spotify_remove_playlist(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """
        Removes a saved Spotify playlist from the user's Spotify library.
        """
        user = await cls.get_session_user(request)
        raw_id = (user.get("discord_user_id") or user.get("id")) if user else None
        if not user or not raw_id:
            return aiohttp.web.json_response({"error": "Authentication required."}, status=401)

        pid = request.match_info.get("id")
        if not pid:
            return aiohttp.web.json_response({"error": "Missing playlist ID."}, status=400)

        discord_user_id = int(raw_id)
        auth_mgr = SpotifyUserAuthManager.get_instance()
        success = await auth_mgr.remove_user_spotify_playlist(discord_user_id, pid)
        return aiohttp.web.json_response({"success": success})

    @classmethod
    async def handle_public_status(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """
        Genuine real-time telemetry endpoint powering /status and /api/status.
        All metrics are measured live from the running process, Discord client,
        voice queues, Audio engine, and database (no synthetic fallback values).
        """
        import math
        import os
        import platform

        try:
            import discord
            discord_ver = discord.__version__
            opus_loaded = bool(discord.opus.is_loaded())
        except Exception:
            discord_ver = "unknown"
            opus_loaded = False

        bot = request.app.get("bot")
        now = time.time()

        # 1. Real Discord gateway readiness & latency
        is_closed = bool(bot and getattr(bot, "is_closed", None) and bot.is_closed() is True)
        is_ready = bool(bot and callable(getattr(bot, "is_ready", None)) and bot.is_ready() and not is_closed)

        ping_ms: Optional[float] = None
        if bot and hasattr(bot, "latency") and bot.latency is not None:
            try:
                lat = float(bot.latency)
                if not math.isinf(lat) and not math.isnan(lat) and lat >= 0:
                    ping_ms = round(lat * 1000, 1)
            except Exception:
                ping_ms = None

        # 2. Real process uptime since boot
        start_time = getattr(bot, "start_time", None) if bot else None
        if not isinstance(start_time, (int, float)) or start_time <= 0:
            start_time = request.app.get("_start_time") or now

        uptime_seconds = max(0, int(now - start_time))
        days = uptime_seconds // 86400
        hours = (uptime_seconds % 86400) // 3600
        minutes = (uptime_seconds % 3600) // 60
        seconds = uptime_seconds % 60
        if days > 0:
            uptime_formatted = f"{days}d {hours}h {minutes}m"
        elif hours > 0:
            uptime_formatted = f"{hours}h {minutes}m {seconds}s"
        else:
            uptime_formatted = f"{minutes}m {seconds}s"

        # 3. Live guilds, listeners, voice sessions, active radio streams
        guilds_count = 0
        total_users = 0
        active_voice = 0
        active_radio = 0
        total_listeners = 0
        queued_tracks_count = 0
        autoplay_sessions = 0

        if bot and hasattr(bot, "guilds"):
            try:
                guilds = list(bot.guilds)
                guilds_count = len(guilds)
            except Exception:
                guilds = []
            music_service = MusicService.get_instance()
            for g in guilds:
                mc = getattr(g, "member_count", 0)
                if isinstance(mc, int):
                    total_users += mc
                vc = getattr(g, "voice_client", None)
                if vc and callable(getattr(vc, "is_connected", None)) and vc.is_connected() is True:
                    active_voice += 1
                    channel = getattr(vc, "channel", None)
                    if channel and hasattr(channel, "members"):
                        total_listeners += len([m for m in channel.members if not getattr(m, "bot", False)])
                try:
                    q = music_service.get_queue(g.id)
                    if q:
                        queued_tracks_count += len(getattr(q, "tracks", []) or [])
                        if getattr(q, "autoplay", False):
                            autoplay_sessions += 1
                        if getattr(q, "active_radio_station", None) or (q.current_track and getattr(q.current_track, "is_radio", False)):
                            active_radio += 1
                except Exception:
                    pass

        # 4. Real DB round-trip health check & logged play count
        db_ok = False
        db_latency_ms: Optional[float] = None
        total_plays_logged = 0
        db_engine = "PostgreSQL" if getattr(db, "is_postgres", False) else "SQLite"
        try:
            t0 = time.perf_counter()
            await db.fetchval("SELECT 1")
            db_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            total_plays_logged = int(await db.fetchval("SELECT COUNT(*) FROM listening_history") or 0)
            db_ok = True
        except Exception as db_err:
            log.debug(f"[Status Telemetry DB Check] {db_err}")
            db_ok = False

        # 5. Live subsystem counts (Audia AI profiles & Radio stations)
        ap_svc = AutoPlayService.get_instance()
        audia_profiles_count = len(getattr(ap_svc, "_profiles", {}) or {})
        radio_countries_count = 0
        try:
            from services.radio_service import RadioService
            r_svc = RadioService.get_instance()
            radio_countries_count = len(r_svc.get_countries() or [])
        except Exception:
            pass

        # 6. Genuine OS / Process resource telemetry (None if sandbox blocks reading, never fabricated)
        cpu_pct: Optional[float] = None
        memory_info: Dict[str, Any] = {"percent": None, "used_mb": None, "total_mb": None, "process_rss_mb": None}
        try:
            import psutil
            proc = psutil.Process(os.getpid())
            memory_info["process_rss_mb"] = round(proc.memory_info().rss / (1024 * 1024), 1)
            mem = psutil.virtual_memory()
            memory_info["percent"] = round(float(mem.percent), 1)
            memory_info["used_mb"] = round(mem.used / (1024 * 1024), 1)
            memory_info["total_mb"] = round(mem.total / (1024 * 1024), 1)
            cpu_val = psutil.cpu_percent(interval=None)
            if isinstance(cpu_val, (int, float)):
                cpu_pct = round(float(cpu_val), 1)
        except Exception:
            try:
                if os.path.exists("/proc/self/status"):
                    with open("/proc/self/status", "r", encoding="utf-8", errors="ignore") as f:
                        for ln in f:
                            if ln.startswith("VmRSS:"):
                                kb = int(ln.split()[1])
                                memory_info["process_rss_mb"] = round(kb / 1024.0, 1)
                                break
            except Exception:
                pass

        # WebSocket active dashboard clients
        try:
            from services.web.websocket import DashboardWebSocketManager
            ws_mgr = DashboardWebSocketManager.get_instance()
            ws_clients = len(getattr(ws_mgr, "connections", None) or getattr(ws_mgr, "_connections", []) or [])
        except Exception:
            ws_clients = 0

        if is_closed:
            overall_status = "offline"
        elif is_ready and db_ok:
            overall_status = "operational" if opus_loaded else "degraded"
        elif bot is None:
            overall_status = "degraded" if not db_ok else "initializing"
        else:
            overall_status = "degraded"

        services = [
            {
                "id": "gateway",
                "name": "Discord Gateway & Commands",
                "status": "operational" if is_ready else ("offline" if is_closed else "starting"),
                "latency_ms": ping_ms,
                "detail": f"{guilds_count} connected server(s)" if is_ready else "Gateway handshake pending"
            },
            {
                "id": "audio_engine",
                "name": "Voice & Opus Audio Pipeline",
                "status": "operational" if opus_loaded else "degraded",
                "active_streams": active_voice,
                "listeners": total_listeners,
                "detail": f"libopus {'loaded' if opus_loaded else 'missing'} • {active_voice} active stream(s)"
            },
            {
                "id": "radio_directory",
                "name": "Radio Directory Resolver",
                "status": "operational" if radio_countries_count > 0 else "degraded",
                "active_stations": active_radio,
                "detail": f"{radio_countries_count} countries indexed • {active_radio} active radio feed(s)"
            },
            {
                "id": "audia_ai",
                "name": "Audia AI Taste & AutoPlay",
                "status": "operational",
                "detail": f"{audia_profiles_count} taste profile(s) • {autoplay_sessions} active AutoPlay queue(s)"
            },
            {
                "id": "database",
                "name": f"{db_engine} Persistence",
                "status": "operational" if db_ok else "down",
                "latency_ms": db_latency_ms,
                "detail": f"{total_plays_logged} logged play(s)" + (f" • {db_latency_ms}ms query" if db_latency_ms is not None else " • check failed")
            },
            {
                "id": "web_dashboard",
                "name": "Unified Web Server & WebSocket",
                "status": "operational",
                "ws_clients": ws_clients,
                "detail": f"{ws_clients} active WebSocket client(s)"
            }
        ]

        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }

        bot_user = getattr(bot, "user", None) if bot else None
        bot_name = str(bot_user) if bot_user else "SyncInk Radio"
        bot_id = str(getattr(bot_user, "id", "1500567606648897819")) if bot_user else "1500567606648897819"

        return aiohttp.web.json_response({
            "status": overall_status,
            "is_online": is_ready,
            "bot_name": bot_name,
            "bot_id": bot_id,
            "ping_ms": ping_ms,
            "db_latency_ms": db_latency_ms,
            "db_engine": db_engine,
            "opus_loaded": opus_loaded,
            "uptime_seconds": uptime_seconds,
            "uptime_formatted": uptime_formatted,
            "start_time": int(start_time),
            "guilds": guilds_count,
            "users": total_users,
            "active_voice": active_voice,
            "active_radio": active_radio,
            "listeners": total_listeners,
            "queued_tracks": queued_tracks_count,
            "total_plays_logged": total_plays_logged,
            "audia_profiles": audia_profiles_count,
            "ws_clients": ws_clients,
            "cpu_percent": cpu_pct,
            "memory": memory_info,
            "platform": f"{platform.system()} {platform.release()}",
            "python_version": platform.python_version(),
            "discord_version": discord_ver,
            "services": services,
            "support_url": "https://discord.gg/PmxfJwmQuB",
            "timestamp": int(now)
        }, headers=headers)
