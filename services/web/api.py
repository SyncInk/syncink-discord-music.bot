import os
import time
import json
import random
from datetime import datetime
from typing import Optional, Dict, Any
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
    """REST endpoints powering the SyncInk Radio Dashboard."""

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

    # ------------------ Auth Endpoints ------------------

    @classmethod
    async def handle_login(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        auth_mgr = DashboardAuthManager.get_instance()
        login_url = auth_mgr.get_login_url()
        raise aiohttp.web.HTTPFound(login_url)

    @classmethod
    async def handle_oauth_callback(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        code = request.query.get("code")
        error = request.query.get("error")

        if error or not code:
            log.warning(f"[Dashboard API] OAuth callback error: {error}")
            raise aiohttp.web.HTTPFound("/?auth_error=" + (error or "missing_code"))

        auth_mgr = DashboardAuthManager.get_instance()
        token_data = await auth_mgr.exchange_code(code)
        if not token_data or "access_token" not in token_data:
            raise aiohttp.web.HTTPFound("/?auth_error=token_exchange_failed")

        user_data = await auth_mgr.fetch_user(token_data["access_token"])
        if not user_data:
            raise aiohttp.web.HTTPFound("/?auth_error=fetch_user_failed")

        session_id = await auth_mgr.create_session(user_data, token_data)

        response = aiohttp.web.HTTPFound("/")
        response.set_cookie(
            "syncink_session",
            session_id,
            max_age=30 * 86400,
            httponly=True,
            samesite="Lax",
            secure=request.scheme == "https"
        )
        return response

    @classmethod
    async def handle_me(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"authenticated": False, "user": None})

        avatar_url = None
        if user.get("avatar"):
            avatar_url = f"https://cdn.discordapp.com/avatars/{user['discord_user_id']}/{user['avatar']}.png?size=256"
        else:
            avatar_url = "https://files.catbox.moe/74l9su.png"

        return aiohttp.web.json_response({
            "authenticated": True,
            "user": {
                "id": str(user["discord_user_id"]),
                "username": user.get("username"),
                "discriminator": user.get("discriminator"),
                "avatar_url": avatar_url,
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

    # ------------------ Servers & Playback Endpoints ------------------

    @classmethod
    async def handle_get_servers(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        bot = request.app.get("bot")
        user = await cls.get_session_user(request)

        user_guild_ids = set()
        user_guilds_map = {}

        if user and user.get("access_token"):
            auth_mgr = DashboardAuthManager.get_instance()
            guilds = await auth_mgr.fetch_user_guilds(user["access_token"])
            for g in guilds:
                gid = int(g["id"])
                user_guild_ids.add(gid)
                user_guilds_map[gid] = g

        server_list = []
        if bot:
            for g in bot.guilds:
                is_member = g.id in user_guild_ids if user else True
                if not is_member and user:
                    continue

                icon_url = str(g.icon.url) if g.icon else "https://files.catbox.moe/74l9su.png"
                queue = MusicService.get_instance().get_queue(g.id)
                vc = g.voice_client

                # Permission badge
                perm = "listener"
                if user:
                    member = g.get_member(user["discord_user_id"])
                    if g.owner_id == user["discord_user_id"]:
                        perm = "owner"
                    elif member and member.guild_permissions.administrator:
                        perm = "admin"
                    elif member and (member.guild_permissions.manage_guild or member.guild_permissions.manage_channels):
                        perm = "dj"

                server_list.append({
                    "id": str(g.id),
                    "name": g.name,
                    "icon": icon_url,
                    "member_count": g.member_count,
                    "connected": bool(vc and vc.is_connected()),
                    "voice_channel": vc.channel.name if vc and vc.channel else None,
                    "listeners": len([m for m in vc.channel.members if not m.bot]) if vc and vc.channel else 0,
                    "current_track": queue.current_track.clean_title if queue.current_track else None,
                    "is_playing": bool(vc and vc.is_playing()),
                    "permission": perm,
                })

        return aiohttp.web.json_response({"servers": server_list})

    @classmethod
    async def handle_get_server_detail(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        guild_id_str = request.match_info.get("guild_id")
        try:
            guild_id = int(guild_id_str)
        except (ValueError, TypeError):
            return aiohttp.web.json_response({"error": "Invalid guild_id"}, status=400)

        bot = request.app.get("bot")
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
        bot = request.app.get("bot")
        service = MusicService.get_instance()
        queue = service.get_queue(guild_id)

        guild = bot.get_guild(guild_id) if bot else None
        vc = (guild.voice_client if guild else None) or queue.voice_client

        if action == "play":
            query = body.get("query")
            if not query:
                return aiohttp.web.json_response({"error": "Missing query parameter"}, status=400)

            # Auto-join if user specifies voice channel or if bot already connected
            voice_channel_id = body.get("voice_channel_id")
            if not vc or not vc.is_connected():
                if guild and voice_channel_id:
                    v_chan = guild.get_channel(int(voice_channel_id))
                    if v_chan:
                        try:
                            vc = await v_chan.connect()
                            queue.voice_client = vc
                        except Exception as ce:
                            log.warning(f"Voice connect error: {ce}")

            try:
                tracks = await service.search_and_extract(query, None, limit=1)
                if tracks:
                    track = tracks[0]
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

        elif action == "resume":
            if vc and vc.is_paused():
                vc.resume()

        elif action == "skip":
            if queue.current_track:
                is_radio = queue.current_track.is_radio or queue.current_track.platform == "radio"
                if is_radio:
                    music_cog = bot.get_cog("Music") if bot else None
                    if music_cog:
                        await music_cog.skip_to_next_radio_station(queue)
                else:
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
                val = max(1, min(200, int(vol)))
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

        # Broadcast update over WebSocket
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

        bot = request.app.get("bot")
        guild = bot.get_guild(guild_id) if bot else None

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
            "music_channel_id": str(settings.get("music_channel_id")) if settings.get("music_channel_id") else None,
            "dj_role_id": str(settings.get("dj_role_id")) if settings.get("dj_role_id") else None,
            "max_volume": settings.get("max_volume", 150),
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

        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"error": "Authentication required"}, status=401)

        body = await request.json()
        music_channel_id = int(body.get("music_channel_id")) if body.get("music_channel_id") else None
        dj_role_id = int(body.get("dj_role_id")) if body.get("dj_role_id") else None

        query = """
            INSERT INTO guild_settings (guild_id, music_channel_id, dj_role_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id) DO UPDATE SET
                music_channel_id = EXCLUDED.music_channel_id,
                dj_role_id = EXCLUDED.dj_role_id;
        """
        await db.execute(query, guild_id, music_channel_id, dj_role_id)
        return aiohttp.web.json_response({"success": True})

    # ------------------ Radio Directory Endpoints ------------------

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
        limit = min(100, int(request.query.get("limit", 60)))

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

        clean_stations = []
        for s in stations:
            clean_stations.append({
                "stationuuid": s.get("stationuuid"),
                "name": s.get("name"),
                "url": s.get("url_resolved") or s.get("url"),
                "favicon": s.get("favicon") or "https://files.catbox.moe/74l9su.png",
                "country": s.get("country") or country,
                "tags": s.get("tags", ""),
                "votes": s.get("votes", 0),
                "bitrate": s.get("bitrate", 128)
            })

        return aiohttp.web.json_response({"stations": clean_stations, "count": len(clean_stations)})

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
        bot = request.app.get("bot")
        music_cog = bot.get_cog("Music") if bot else None
        if not music_cog:
            return aiohttp.web.json_response({"error": "Music service unavailable"}, status=503)

        service = MusicService.get_instance()
        queue = service.get_queue(guild_id)

        station_dict = {
            "name": station_name or "Live Radio",
            "url": stream_url,
            "url_resolved": stream_url,
            "favicon": body.get("favicon", ""),
            "country": country
        }

        from cogs.music import make_radio_track
        track = make_radio_track(station_dict, country, None)
        queue.active_radio_station = country
        queue.active_radio_station_info = station_dict
        queue.tracks.clear()

        await music_cog.play_track(queue, track)
        await DashboardWebSocketManager.get_instance().broadcast_playback_update(guild_id, bot)

        return aiohttp.web.json_response({"success": True, "station": station_name})

    # ------------------ Audia AI Endpoints ------------------

    @classmethod
    async def handle_get_audia_profile(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        user_id = user["discord_user_id"] if user else 0

        prof = AutoPlayService.get_instance().get_user_profile(user_id)

        clean_artists = [
            {"artist": a, "affinity": round(score, 1)}
            for a, score in sorted(prof.artist_affinity.items(), key=lambda x: x[1], reverse=True)[:15]
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
        action = body.get("action")  # like, dislike, block
        artist = body.get("artist")
        track_title = body.get("track_title")

        prof = AutoPlayService.get_instance().get_user_profile(user["discord_user_id"])
        if action == "block" and artist:
            if artist not in prof.blocked_artists:
                prof.blocked_artists.append(artist)
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

    # ------------------ Library & History Endpoints ------------------

    @classmethod
    async def handle_get_favorites(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        if not user:
            return aiohttp.web.json_response({"favorites": []})

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
        image_url = body.get("image_url", "")
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
    async def handle_get_history(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        limit = min(100, int(request.query.get("limit", 50)))

        query = """
            SELECT * FROM listening_history
            WHERE ($1 = 0 OR discord_user_id = $1)
            ORDER BY played_at DESC
            LIMIT $2
        """
        uid = user["discord_user_id"] if user else 0
        rows = await db.fetch(query, uid, limit)
        history = [dict(r) for r in rows]
        for h in history:
            if isinstance(h.get("played_at"), datetime):
                h["played_at"] = h["played_at"].isoformat()

        return aiohttp.web.json_response({"history": history})

    @classmethod
    async def handle_get_analytics(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user = await cls.get_session_user(request)
        uid = user["discord_user_id"] if user else 0

        # Aggregated stats from history
        total_songs_row = await db.fetchrow(
            "SELECT COUNT(*) as count, COALESCE(SUM(duration), 0) as total_seconds FROM listening_history WHERE ($1 = 0 OR discord_user_id = $1)",
            uid
        )
        total_songs = total_songs_row["count"] if total_songs_row else 0
        total_seconds = total_songs_row["total_seconds"] if total_songs_row else 0

        top_artists_rows = await db.fetch(
            "SELECT track_author, COUNT(*) as play_count FROM listening_history WHERE ($1 = 0 OR discord_user_id = $1) AND track_author IS NOT NULL GROUP BY track_author ORDER BY play_count DESC LIMIT 7",
            uid
        )
        top_artists = [dict(r) for r in top_artists_rows]

        top_tracks_rows = await db.fetch(
            "SELECT track_title, track_author, thumbnail_url, COUNT(*) as play_count FROM listening_history WHERE ($1 = 0 OR discord_user_id = $1) GROUP BY track_title, track_author, thumbnail_url ORDER BY play_count DESC LIMIT 7",
            uid
        )
        top_tracks = [dict(r) for r in top_tracks_rows]

        return aiohttp.web.json_response({
            "total_tracks": total_songs,
            "total_seconds": total_seconds,
            "total_hours": round(total_seconds / 3600.0, 1),
            "top_artists": top_artists,
            "top_tracks": top_tracks,
        })

    # ------------------ Admin & Status Endpoints ------------------

    @classmethod
    async def handle_admin_status(cls, request: aiohttp.web.Request) -> aiohttp.web.Response:
        bot = request.app.get("bot")

        guilds_count = len(bot.guilds) if bot else 0
        active_voice = 0
        active_radio = 0

        if bot:
            for g in bot.guilds:
                if g.voice_client and g.voice_client.is_connected():
                    active_voice += 1
                queue = MusicService.get_instance().get_queue(g.id)
                if queue.active_radio_station or (queue.current_track and queue.current_track.is_radio):
                    active_radio += 1

        return aiohttp.web.json_response({
            "status": "online",
            "bot_name": str(bot.user) if bot and bot.user else "SyncInk Radio",
            "guilds": guilds_count,
            "active_voice_sessions": active_voice,
            "active_radio_streams": active_radio,
            "latency_ms": round(bot.latency * 1000, 1) if bot else 0,
            "web_clients": len(DashboardWebSocketManager.get_instance()._active_sockets),
            "timestamp": time.time(),
        })
