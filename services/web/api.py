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
            avatar_url = "https://files.catbox.moe/74l9su.png"

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
                "avatar_url": "https://files.catbox.moe/74l9su.png",
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
                "icon": "https://files.catbox.moe/74l9su.png",
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
                "icon": "https://files.catbox.moe/74l9su.png",
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

                icon_url = str(g.icon.url) if g.icon else "https://files.catbox.moe/74l9su.png"
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
                    "can_manage": can_manage
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
        if not member:
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
            if not vc or not vc.is_connected():
                if guild:
                    target_vc = None
                    if voice_channel_id:
                        target_vc = guild.get_channel(int(voice_channel_id))
                    elif guild.voice_channels:
                        # Auto-pick non-empty voice channel or first voice channel
                        for ch in guild.voice_channels:
                            if any(not m.bot for m in ch.members):
                                target_vc = ch
                                break
                        if not target_vc:
                            target_vc = guild.voice_channels[0]
                    if target_vc:
                        try:
                            vc = await target_vc.connect()
                            queue.voice_client = vc
                        except Exception as ce:
                            log.warning(f"Voice connect error: {ce}")

            try:
                requester = member or SimpleNamespace(id=user_id, name=user.get("username", "Dashboard User"), display_name=user.get("username", "Dashboard User"), mention=f"<@{user_id}>", bot=False)
                tracks = await service.search_and_extract(query, requester, limit=1)
                if tracks:
                    track = tracks[0]
                    track.requested_by = requester
                    if not queue.current_track:
                        music_cog = bot.get_cog("Music") if bot else None
                        if music_cog:
                            await music_cog.play_track(queue, track)
                    else:
                        queue.tracks.append(track)
            except Exception as pe:
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
                "favicon": s.get("favicon") or "https://files.catbox.moe/74l9su.png",
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
            "favicon": body.get("favicon", "https://files.catbox.moe/74l9su.png"),
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
        await DashboardWebSocketManager.get_instance().broadcast_playback_update(guild_id, bot)

        return aiohttp.web.json_response({"success": True, "station": station_name})

    # ------------------ 4. Audia AI Engine ------------------

    @classmethod
    async def handle_get_audia_profile(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        user_id = user["discord_user_id"] if user else 0

        prof = AutoPlayService.get_instance().get_user_profile(user_id)

        clean_artists = [
            {"artist": a, "affinity": round(score, 1)}
            for a, score in sorted(prof.artist_affinity.items(), key=lambda x: x[1], reverse=True)[:20]
            if a and not any(l in a.lower() for l in ["t-series", "sony music", "zee music", "tips", "yrf", "saregama"])
        ]

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
            "blocked_artists": prof.blocked_artists,
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

        prof = AutoPlayService.get_instance().get_user_profile(user["discord_user_id"])
        if action == "block" and artist:
            if artist not in prof.blocked_artists:
                prof.blocked_artists.append(artist)
        elif action == "unblock" and artist:
            if artist in prof.blocked_artists:
                prof.blocked_artists.remove(artist)
        elif action == "like" and track_title:
            prof.liked_tracks[track_title] = time.time()
            if artist:
                prof.artist_affinity[artist] = prof.artist_affinity.get(artist, 1.0) + 1.5
        elif action == "dislike" and track_title:
            prof.disliked_tracks[track_title] = time.time()
            if artist:
                prof.artist_affinity[artist] = max(0.1, prof.artist_affinity.get(artist, 1.0) - 1.0)

        AutoPlayService.get_instance().save_profiles()
        return aiohttp.web.json_response({"success": True})

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
        image_url = body.get("image_url", "https://files.catbox.moe/74l9su.png")
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
        thumbnail = body.get("thumbnail", "https://files.catbox.moe/74l9su.png")
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

    # ------------------ 6. History & Analytics ------------------

    @classmethod
    async def handle_get_history(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        timeframe = request.query.get("timeframe", "all")
        query_text = request.query.get("query", "").strip().lower()
        limit = min(150, int(request.query.get("limit", 50)))

        uid = user["discord_user_id"] if user else 0

        time_clause = ""
        now = datetime.utcnow()
        if timeframe == "24h":
            since = now - timedelta(days=1)
            time_clause = f"AND played_at >= '{since.strftime('%Y-%m-%d %H:%M:%S')}'"
        elif timeframe == "7d":
            since = now - timedelta(days=7)
            time_clause = f"AND played_at >= '{since.strftime('%Y-%m-%d %H:%M:%S')}'"
        elif timeframe == "30d":
            since = now - timedelta(days=30)
            time_clause = f"AND played_at >= '{since.strftime('%Y-%m-%d %H:%M:%S')}'"

        filter_clause = ""
        if query_text:
            filter_clause = f"AND (LOWER(track_title) LIKE '%{query_text}%' OR LOWER(track_author) LIKE '%{query_text}%')"

        bot = request.app.get("bot")
        accessible_guild_ids = []
        if bot and uid:
            for g in bot.guilds:
                if g.get_member(uid):
                    accessible_guild_ids.append(g.id)

        if accessible_guild_ids:
            guild_list_str = ",".join(str(gid) for gid in accessible_guild_ids)
            user_clause = f"WHERE (discord_user_id = $1 OR (guild_id IN ({guild_list_str}) AND (discord_user_id = 0 OR discord_user_id = $1)))"
        else:
            user_clause = "WHERE ($1 = 0 OR discord_user_id = $1)"

        query = f"""
            SELECT * FROM listening_history
            {user_clause}
            {time_clause}
            {filter_clause}
            ORDER BY played_at DESC
            LIMIT $2
        """
        rows = await db.fetch(query, uid, limit)
        history = [dict(r) for r in rows]
        for h in history:
            if isinstance(h.get("played_at"), datetime):
                h["played_at"] = h["played_at"].isoformat()

        return aiohttp.web.json_response({"history": history, "count": len(history), "authenticated": bool(user)})

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
        return aiohttp.web.json_response({"success": True})

    @classmethod
    async def handle_get_analytics(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({
                "authenticated": False,
                "timeframe": "7d",
                "total_tracks": 0,
                "total_seconds": 0,
                "total_hours": 0.0,
                "peak_listening_hour": "--",
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

        uid = user["discord_user_id"]
        timeframe = request.query.get("timeframe", "7d")

        now = datetime.utcnow()
        time_clause = ""
        if timeframe == "24h":
            since = now - timedelta(days=1)
            time_clause = f"AND played_at >= '{since.strftime('%Y-%m-%d %H:%M:%S')}'"
        elif timeframe == "7d":
            since = now - timedelta(days=7)
            time_clause = f"AND played_at >= '{since.strftime('%Y-%m-%d %H:%M:%S')}'"
        elif timeframe == "30d":
            since = now - timedelta(days=30)
            time_clause = f"AND played_at >= '{since.strftime('%Y-%m-%d %H:%M:%S')}'"
        elif timeframe == "90d":
            since = now - timedelta(days=90)
            time_clause = f"AND played_at >= '{since.strftime('%Y-%m-%d %H:%M:%S')}'"

        bot = request.app.get("bot")
        accessible_guild_ids = []
        if bot and uid:
            for g in bot.guilds:
                if g.get_member(uid):
                    accessible_guild_ids.append(g.id)

        if accessible_guild_ids:
            guild_list_str = ",".join(str(gid) for gid in accessible_guild_ids)
            user_clause = f"WHERE (discord_user_id = $1 OR (guild_id IN ({guild_list_str}) AND (discord_user_id = 0 OR discord_user_id = $1)))"
        else:
            user_clause = "WHERE ($1 = 0 OR discord_user_id = $1)"

        # Totals
        total_songs_row = await db.fetchrow(
            f"SELECT COUNT(*) as count, COALESCE(SUM(duration), 0) as total_seconds FROM listening_history {user_clause} {time_clause}",
            uid
        )
        total_songs = total_songs_row["count"] if total_songs_row else 0
        total_seconds = total_songs_row["total_seconds"] if total_songs_row else 0

        # Top Artists
        top_artists_rows = await db.fetch(
            f"SELECT track_author, COUNT(*) as play_count FROM listening_history {user_clause} AND track_author IS NOT NULL {time_clause} GROUP BY track_author ORDER BY play_count DESC LIMIT 8",
            uid
        )
        top_artists = [dict(r) for r in top_artists_rows]

        # Top Tracks
        top_tracks_rows = await db.fetch(
            f"SELECT track_title, track_author, thumbnail_url, COUNT(*) as play_count FROM listening_history {user_clause} {time_clause} GROUP BY track_title, track_author, thumbnail_url ORDER BY play_count DESC LIMIT 8",
            uid
        )
        top_tracks = [dict(r) for r in top_tracks_rows]

        # Hourly Distribution (0-23 hours for peak listening activity)
        history_rows = await db.fetch(
            f"SELECT played_at FROM listening_history {user_clause} {time_clause} ORDER BY played_at DESC LIMIT 500",
            uid
        )
        hourly_counts = [0] * 24
        for r in history_rows:
            dt = r.get("played_at")
            if isinstance(dt, datetime):
                hourly_counts[dt.hour] += 1
            elif isinstance(dt, str):
                try:
                    parsed = datetime.fromisoformat(dt.replace("Z", ""))
                    hourly_counts[parsed.hour] += 1
                except Exception:
                    pass

        peak_hour = hourly_counts.index(max(hourly_counts)) if max(hourly_counts) > 0 else 20
        peak_hour_str = f"{peak_hour:02d}:00 - {(peak_hour+1)%24:02d}:00"

        # Platform distribution
        platform_rows = await db.fetch(
            f"SELECT platform, COUNT(*) as count FROM listening_history {user_clause} {time_clause} GROUP BY platform",
            uid
        )
        platforms = {dict(r)["platform"]: dict(r)["count"] for r in platform_rows}

        # Real-time live status from active playing voice channel
        live_active = False
        live_track = None
        live_guild_name = None
        live_channel_name = None
        live_elapsed = 0

        if bot and accessible_guild_ids:
            music_service = MusicService.get_instance()
            for gid in accessible_guild_ids:
                q = music_service.get_queue(gid)
                if q.voice_client and q.voice_client.is_playing() and q.current_track:
                    live_active = True
                    live_track = {
                        "title": q.current_track.clean_title,
                        "author": q.current_track.author,
                        "thumbnail": q.current_track.thumbnail,
                        "duration": q.current_track.duration,
                        "is_radio": q.current_track.is_radio
                    }
                    g = bot.get_guild(gid)
                    live_guild_name = g.name if g else "Discord Server"
                    live_channel_name = q.voice_client.channel.name if q.voice_client.channel else "Voice"
                    if q.track_start_time:
                        live_elapsed = max(0, int(time.time() - q.track_start_time - q.total_paused_duration))
                    break

        return aiohttp.web.json_response({
            "authenticated": True,
            "timeframe": timeframe,
            "total_tracks": total_songs,
            "total_seconds": total_seconds + live_elapsed,
            "total_hours": round((total_seconds + live_elapsed) / 3600.0, 2),
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
