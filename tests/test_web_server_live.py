import asyncio
import unittest
from unittest.mock import MagicMock
from aiohttp.test_utils import AioHTTPTestCase
from services.web.server import UnifiedWebServer
from database import db


class TestLiveWebServer(AioHTTPTestCase):
    async def setUpAsync(self):
        await super().setUpAsync()
        await db.connect()

    async def tearDownAsync(self):
        await db.close()
        await super().tearDownAsync()

    async def get_application(self):
        mock_bot = MagicMock()
        mock_bot.user = MagicMock()
        mock_bot.user.id = 123456789
        mock_bot.user.name = "SyncInk Radio"
        
        mock_guild = MagicMock()
        mock_guild.id = 999111222
        mock_guild.name = "Private Discord Guild"
        mock_guild.icon = None
        mock_guild.owner_id = 111222333
        mock_guild.member_count = 50
        mock_guild.voice_client = None
        mock_guild.get_member = lambda uid: None
        
        mock_bot.guilds = [mock_guild]
        mock_bot.get_guild = lambda gid: mock_guild if gid == 999111222 else None
        
        server = UnifiedWebServer(port=8080, host="127.0.0.1", bot=mock_bot)
        return server.app

    async def test_frontend_routes(self):
        resp = await self.client.request("GET", "/")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("SyncInk Radio", text)
        self.assertIn("Powered by Audia AI", text)
        self.assertNotIn("Audia Audio Engine", text)
        self.assertIn("static/radio-bot.jpg", text)
        self.assertIn("static/syncink-main.jpg", text)
        self.assertIn("toggleDesktopSidebar", text)
        self.assertIn("-right-3.5 top-1/2", text)
        self.assertIn("sidebar-status-card", text)
        self.assertNotIn("header-status-pill", text)
        self.assertNotIn("btn-desktop-sidebar", text)
        self.assertIn("pb-28", text)
        self.assertIn("Commands &amp; Guide", text)
        self.assertIn("FAQ &amp; Help", text)
        self.assertIn("M8.02 15.33", text)
        self.assertIn('fill-rule="evenodd"', text)

        resp_logo = await self.client.request("GET", "/static/radio-bot.jpg")
        self.assertEqual(resp_logo.status, 200)
        resp_sub_logo = await self.client.request("GET", "/dashboard/radio/static/radio-bot.jpg")
        self.assertEqual(resp_sub_logo.status, 200)
        resp_main_logo = await self.client.request("GET", "/static/syncink-main.jpg")
        self.assertEqual(resp_main_logo.status, 200)
        resp_sub_main = await self.client.request("GET", "/dashboard/radio/static/syncink-main.jpg")
        self.assertEqual(resp_sub_main.status, 200)

        resp_css = await self.client.request("GET", "/static/style.css")
        self.assertEqual(resp_css.status, 200)
        css_text = await resp_css.text()
        self.assertIn("#101014", css_text)
        self.assertIn("#sidebar.sidebar-collapsed", css_text)

        resp_js = await self.client.request("GET", "/static/app.js")
        self.assertEqual(resp_js.status, 200)
        js_text = await resp_js.text()
        self.assertIn("toggleDesktopSidebar", js_text)
        self.assertIn("initSidebarToggle", js_text)

    async def test_api_routes(self):
        resp = await self.client.request("GET", "/health")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data.get("status"), "ok")

        resp_user = await self.client.request("GET", "/api/user/me")
        self.assertEqual(resp_user.status, 200)
        user_data = await resp_user.json()
        self.assertFalse(user_data["authenticated"])

        resp_radio = await self.client.request("GET", "/api/radio/stations?limit=5")
        self.assertEqual(resp_radio.status, 200)
        radio_data = await resp_radio.json()
        self.assertIn("stations", radio_data)

        resp_audia = await self.client.request("GET", "/api/audia/recommendations?limit=3")
        self.assertEqual(resp_audia.status, 200)
        audia_data = await resp_audia.json()
        self.assertIn("recommendations", audia_data)

    async def test_websocket_upgrade(self):
        ws = await self.client.ws_connect("/ws")
        welcome = await ws.receive_json()
        self.assertEqual(welcome.get("event"), "connected")

        await ws.send_json({"type": "ping"})
        pong = await ws.receive_json()
        self.assertEqual(pong.get("event"), "pong")
        await ws.close()

    async def test_dashboard_radio_subpath_mounting(self):
        # 1. Subpath redirect from /dashboard/radio to /dashboard/radio/
        resp_redir = await self.client.request("GET", "/dashboard/radio", allow_redirects=False)
        self.assertEqual(resp_redir.status, 302)
        self.assertEqual(resp_redir.headers.get("Location"), "/dashboard/radio/")

        # 2. Subpath index HTML
        resp_sub = await self.client.request("GET", "/dashboard/radio/")
        self.assertEqual(resp_sub.status, 200)
        text = await resp_sub.text()
        self.assertIn("SyncInk Radio", text)
        self.assertIn("SYNCINK_BASE_PATH", text)

        # 3. Subpath static files
        resp_css = await self.client.request("GET", "/dashboard/radio/static/style.css")
        self.assertEqual(resp_css.status, 200)
        self.assertIn("#101014", await resp_css.text())

        resp_js = await self.client.request("GET", "/dashboard/radio/static/app.js")
        self.assertEqual(resp_js.status, 200)

        # 4. Subpath APIs
        resp_health = await self.client.request("GET", "/dashboard/radio/health")
        self.assertEqual(resp_health.status, 200)
        health_data = await resp_health.json()
        self.assertEqual(health_data.get("status"), "ok")

        resp_user = await self.client.request("GET", "/dashboard/radio/api/auth/me")
        self.assertEqual(resp_user.status, 200)

        resp_radio = await self.client.request("GET", "/dashboard/radio/api/radio/stations?limit=3")
        self.assertEqual(resp_radio.status, 200)

        # 5. Subpath WebSocket
        ws_sub = await self.client.ws_connect("/dashboard/radio/ws")
        sub_welcome = await ws_sub.receive_json()
        self.assertEqual(sub_welcome.get("event"), "connected")

        await ws_sub.send_json({"type": "ping"})
        sub_pong = await ws_sub.receive_json()
        self.assertEqual(sub_pong.get("event"), "pong")
        await ws_sub.close()

    async def test_unauthenticated_security_locks(self):
        """Verifies strict 401 Unauthorized blocks on sensitive guild endpoints for guests."""
        # 1. Unauthenticated /api/servers returns 401 and empty servers
        resp = await self.client.request("GET", "/api/servers")
        self.assertEqual(resp.status, 401)
        data = await resp.json()
        self.assertFalse(data.get("authenticated", True))
        self.assertEqual(data.get("servers", []), [])

        # 2. Unauthenticated /api/servers/{id} returns 401
        resp_detail = await self.client.request("GET", "/api/servers/999111222")
        self.assertEqual(resp_detail.status, 401)

        # 3. Unauthenticated /api/servers/{id}/control returns 401
        resp_ctrl = await self.client.request("POST", "/api/servers/999111222/control", json={"action": "play", "query": "test"})
        self.assertEqual(resp_ctrl.status, 401)

        # 4. Unauthenticated /api/servers/{id}/settings returns 401
        resp_get_sett = await self.client.request("GET", "/api/servers/999111222/settings")
        self.assertEqual(resp_get_sett.status, 401)

        resp_post_sett = await self.client.request("POST", "/api/servers/999111222/settings", json={"max_volume": 80})
        self.assertEqual(resp_post_sett.status, 401)

        # 5. Unauthenticated /api/radio/tune returns 401
        resp_tune = await self.client.request("POST", "/api/radio/tune", json={"guild_id": "999111222", "url": "https://stream.mp3", "station_name": "Test"})
        self.assertEqual(resp_tune.status, 401)

    async def test_authenticated_access_control(self):
        """Verifies that authenticated sessions only see and manage servers they belong to."""
        from services.web.auth import DashboardAuthManager
        auth_mgr = DashboardAuthManager.get_instance()

        # Create session for user A (not a member of guild 999111222)
        user_a = {"id": "123450001", "username": "UserA"}
        token_a = {"access_token": "token_a", "expires_in": 3600}
        session_a = await auth_mgr.create_session(user_a, token_a)

        headers_a = {"Cookie": f"syncink_session={session_a}"}

        # User A requests /api/servers -> 200 OK but 0 servers (because User A is not in 999111222)
        resp_a_servers = await self.client.request("GET", "/api/servers", headers=headers_a)
        self.assertEqual(resp_a_servers.status, 200)
        data_a = await resp_a_servers.json()
        self.assertTrue(data_a["authenticated"])
        self.assertEqual(len(data_a["servers"]), 0)

        # User A tries to view detail of guild 999111222 -> 403 Forbidden
        resp_a_detail = await self.client.request("GET", "/api/servers/999111222", headers=headers_a)
        self.assertEqual(resp_a_detail.status, 403)

        # User A tries to control playback on guild 999111222 -> 403 Forbidden
        resp_a_ctrl = await self.client.request("POST", "/api/servers/999111222/control", headers=headers_a, json={"action": "pause"})
        self.assertEqual(resp_a_ctrl.status, 403)

        # User A tries to view settings on guild 999111222 -> 403 Forbidden
        resp_a_sett = await self.client.request("GET", "/api/servers/999111222/settings", headers=headers_a)
        self.assertEqual(resp_a_sett.status, 403)

        await auth_mgr.destroy_session(session_a)

    async def test_legal_status_routes_and_live_telemetry(self):
        """Verifies /privacy, /terms, /status, /guide, /faq direct, subpath, subdomain routing and genuine live /api/status."""
        routes_to_check = [
            ("/privacy", "Privacy Policy"),
            ("/privacy.html", "Privacy Policy"),
            ("/dashboard/radio/privacy", "Privacy Policy"),
            ("/terms", "Terms of Use"),
            ("/terms.html", "Terms of Use"),
            ("/terms-of-use", "Terms of Use"),
            ("/dashboard/radio/terms", "Terms of Use"),
            ("/status", "Real-Time Session Latency Telemetry"),
            ("/status.html", "Real-Time Session Latency Telemetry"),
            ("/dashboard/radio/status", "Real-Time Session Latency Telemetry"),
            ("/guide", "Setup Guide &amp; All Commands"),
            ("/guide.html", "Setup Guide &amp; All Commands"),
            ("/setup", "Setup Guide &amp; All Commands"),
            ("/commands", "Setup Guide &amp; All Commands"),
            ("/dashboard/radio/guide", "Setup Guide &amp; All Commands"),
            ("/faq", "Frequently Asked Questions"),
            ("/faq.html", "Frequently Asked Questions"),
            ("/dashboard/radio/faq", "Frequently Asked Questions"),
        ]
        for path, expected_text in routes_to_check:
            resp = await self.client.request("GET", path)
            self.assertEqual(resp.status, 200, f"Failed for path {path}")
            content = await resp.text()
            self.assertIn(expected_text, content, f"Missing '{expected_text}' in {path}")
            self.assertIn("https://discord.gg/PmxfJwmQuB", content)
            self.assertIn("M8.02 15.33", content, f"Missing complete Discord Clyde eye cutout in {path}")
            self.assertIn('fill-rule="evenodd"', content, f"Missing fill-rule='evenodd' in {path}")

        subdomain_tests = [
            ("privacy.syncink.site", "Privacy Policy"),
            ("terms.syncink.site", "Terms of Use"),
            ("status.syncink.site", "Real-Time Session Latency Telemetry"),
            ("guide.syncink.site", "Setup Guide &amp; All Commands"),
            ("faq.syncink.site", "Frequently Asked Questions"),
        ]
        for host, expected_snippet in subdomain_tests:
            resp = await self.client.request("GET", "/", headers={"Host": host})
            self.assertEqual(resp.status, 200, f"Subdomain failed for {host}")
            self.assertIn(expected_snippet, await resp.text())

        for api_path in ["/api/status", "/api/bot/uptime", "/api/bot/status", "/dashboard/radio/api/status"]:
            resp = await self.client.request("GET", api_path)
            self.assertEqual(resp.status, 200, f"Failed for {api_path}")
            data = await resp.json()
            self.assertIn("status", data)
            self.assertIn("uptime_seconds", data)
            self.assertIn("db_latency_ms", data)
            self.assertIn("services", data)
            self.assertEqual(data.get("support_url"), "https://discord.gg/PmxfJwmQuB")

    async def test_listening_history_artwork_enrichment(self):
        """Verifies null/fallback listening_history posters resolve to official artwork & heal SQLite row."""
        from unittest.mock import AsyncMock, patch
        from services.web.auth import DashboardAuthManager
        from services.artwork_service import ArtworkService

        auth_mgr = DashboardAuthManager.get_instance()
        uid_str = "888222333444555"
        uid = int(uid_str)
        session_id = await auth_mgr.create_session({"id": uid_str, "username": "PosterTester"}, {"access_token": "tok", "expires_in": 3600})
        headers = {"Cookie": f"syncink_session={session_id}"}
        expected_poster = "https://is1-ssl.mzstatic.com/image/thumb/Music/600x600bb.jpg"

        ArtworkService._cache.clear()
        try:
            await db.execute("DELETE FROM listening_history WHERE discord_user_id = $1", uid)
            await db.execute(
                "INSERT INTO listening_history (guild_id, discord_user_id, track_title, track_author, track_url, duration, platform, thumbnail_url) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
                555666777, uid, "UniquePosterTrack2026", "Arijit Singh", "https://youtube.com/watch?v=dQw4w9WgXcQ", 240, "youtube", None
            )

            with patch.object(ArtworkService, "_fetch_itunes_poster", new=AsyncMock(return_value=expected_poster)):
                resp = await self.client.request("GET", "/api/history", headers=headers)
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                matching = [h for h in data.get("history", []) if h.get("track_title") == "UniquePosterTrack2026"]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0]["thumbnail_url"], expected_poster)

            row = await db.fetchrow(
                "SELECT thumbnail_url FROM listening_history WHERE discord_user_id = $1 AND track_title = $2",
                uid, "UniquePosterTrack2026"
            )
            self.assertIsNotNone(row)
            self.assertEqual(row["thumbnail_url"], expected_poster)
        finally:
            await db.execute("DELETE FROM listening_history WHERE discord_user_id = $1", uid)
            ArtworkService._cache.clear()
            await auth_mgr.destroy_session(session_id)

    async def test_artist_block_unblock_and_history_analytics_api(self):
        """Verifies blocking/unblocking artists and cross-guild history & analytics endpoints."""
        from services.web.auth import DashboardAuthManager
        from services.autoplay_service import AutoPlayService

        auth_mgr = DashboardAuthManager.get_instance()
        ap = AutoPlayService.get_instance()
        uid_str = "888111222333444"
        uid = int(uid_str)
        session_id = await auth_mgr.create_session({"id": uid_str, "username": "BlockTester"}, {"access_token": "tok", "expires_in": 3600})
        headers = {"Cookie": f"syncink_session={session_id}"}

        try:
            # 1. Block artist via API
            r_block = await self.client.request("POST", "/api/audia/feedback", headers=headers, json={"action": "block", "artist": "Test Artist"})
            self.assertEqual(r_block.status, 200)
            b_data = await r_block.json()
            self.assertIn("Test Artist", b_data.get("blocked_artists", []))

            # 2. Blocked artist appears in blocked_artists and NOT in top_artists
            r_prof = await self.client.request("GET", "/api/audia/profile", headers=headers)
            self.assertEqual(r_prof.status, 200)
            p_data = await r_prof.json()
            self.assertIn("Test Artist", p_data.get("blocked_artists", []))
            top_names = [a["artist"].lower() for a in p_data.get("top_artists", [])]
            self.assertNotIn("test artist", top_names)

            # 3. Unblock artist case-insensitively via API
            r_unblock = await self.client.request("POST", "/api/audia/feedback", headers=headers, json={"action": "unblock", "artist": "test artist"})
            self.assertEqual(r_unblock.status, 200)
            u_data = await r_unblock.json()
            self.assertEqual(u_data.get("blocked_artists", []), [])

            # 4. Listening History & Analytics (quote-safe query + scope=all vs scope=guild + AP memory)
            await db.execute("DELETE FROM listening_history WHERE discord_user_id = $1", uid)
            await db.execute(
                "INSERT INTO listening_history (guild_id, discord_user_id, track_title, track_author, track_url, duration, platform) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                555666777, uid, "Don't Stop Me Now", "Queen", "https://youtube.com/watch?v=x", 210, "youtube"
            )
            prof = ap.get_user_profile(uid)
            prof.memorized_tracks.append({
                "title": "Legacy Audia Song", "artist": "Arijit Singh", "play_count": 2,
                "first_played": 1795000000.0, "last_played": 1795000000.0
            })

            # History with unrelated active guild_id (default scope='all') STILL shows user tracks & safely searches apostrophe
            r_hist = await self.client.request("GET", "/api/history?guild_id=999111222&query=don't", headers=headers)
            self.assertEqual(r_hist.status, 200)
            h_data = await r_hist.json()
            self.assertGreaterEqual(len(h_data.get("history", [])), 1)
            self.assertEqual(h_data["history"][0]["track_title"], "Don't Stop Me Now")

            # History without query includes both DB row and Audia memorized record
            r_hist_all = await self.client.request("GET", "/api/history?guild_id=999111222", headers=headers)
            all_titles = {item["track_title"] for item in (await r_hist_all.json()).get("history", [])}
            self.assertIn("Don't Stop Me Now", all_titles)
            self.assertIn("Legacy Audia Song", all_titles)

            # History strictly scoped to unrelated guild has 0 tracks
            r_hist_guild = await self.client.request("GET", "/api/history?guild_id=999111222&scope=guild", headers=headers)
            g_data = await r_hist_guild.json()
            self.assertEqual(len(g_data.get("history", [])), 0)

            # Analytics default timeframe includes user records & real totals
            r_an = await self.client.request("GET", "/api/analytics?guild_id=999111222", headers=headers)
            self.assertEqual(r_an.status, 200)
            an_data = await r_an.json()
            self.assertGreaterEqual(an_data.get("total_tracks", 0), 3)
            self.assertGreater(an_data.get("total_seconds", 0), 0)
        finally:
            await db.execute("DELETE FROM listening_history WHERE discord_user_id = $1", uid)
            ap._profiles.pop(uid, None)
            ap.save_profiles()
            await auth_mgr.destroy_session(session_id)

    async def test_realtime_lyrics_endpoint_and_ui_markup(self):
        """Verifies /api/lyrics, /dashboard/radio/api/lyrics, radio gating, auth gating, and frontend lyrics DOM."""
        from unittest.mock import AsyncMock, patch
        from services.lyrics_service import LyricsService

        fake_lyrics = {
            "found": True,
            "synced": True,
            "instrumental": False,
            "track_title": "Mock Track",
            "artist_name": "Mock Artist",
            "album_name": "Mock Album",
            "duration": 180,
            "source": "LRCLIB",
            "lines": [
                {"time": 1.5, "text": "First glowing lyric line"},
                {"time": 6.0, "text": "Second glowing lyric line"},
            ],
            "plain_lines": ["First glowing lyric line", "Second glowing lyric line"],
            "plain_lyrics": "First glowing lyric line\nSecond glowing lyric line",
        }

        with patch.object(LyricsService, "get_lyrics", new=AsyncMock(return_value=dict(fake_lyrics))):
            for path in ("/api/lyrics?title=Mock%20Track&artist=Mock%20Artist", "/dashboard/radio/api/lyrics?title=Mock%20Track"):
                resp = await self.client.request("GET", path)
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertTrue(data["found"])
                self.assertTrue(data["synced"])
                self.assertEqual(len(data["lines"]), 2)
                self.assertEqual(data["lines"][0]["text"], "First glowing lyric line")

        # Demo Radio Guild reports live radio safely without faking lyrics
        r_radio = await self.client.request("GET", "/api/lyrics?guild_id=110000000000000002")
        self.assertEqual(r_radio.status, 200)
        radio_data = await r_radio.json()
        self.assertTrue(radio_data.get("is_radio"))
        self.assertFalse(radio_data.get("found"))

        # Real guild without authentication & without explicit title rejects with 401
        r_unauth = await self.client.request("GET", "/api/lyrics?guild_id=999111222")
        self.assertEqual(r_unauth.status, 401)

        # Verify desktop & mobile lyrics hooks in served assets
        index_text = await (await self.client.request("GET", "/")).text()
        self.assertIn("lyrics-panel", index_text)
        self.assertIn("mfp-lyrics-lines", index_text)
        self.assertIn("spotlight-lyrics-btn", index_text)
        self.assertIn("player-btn-lyrics", index_text)
        css_text = await (await self.client.request("GET", "/static/style.css")).text()
        self.assertIn(".lyric-line.lyric-active", css_text)
        self.assertIn("--lyric-progress", css_text)
        js_text = await (await self.client.request("GET", "/static/app.js")).text()
        self.assertIn("initLyricsSystem", js_text)
        self.assertIn("syncLyricsActiveLine", js_text)
        self.assertIn("switchMobilePlayerTab", js_text)

    async def test_dashboard_play_control_and_json_error_middleware(self):
        """Verifies dashboard play control works end-to-end without asyncio NameError, handles error JSON cleanly, and keeps toasts spam-free."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        from services.web.auth import DashboardAuthManager
        from services.music_service import MusicService, Track
        from services.web.api import DashboardAPI

        auth_mgr = DashboardAuthManager.get_instance()
        owner_user = {"id": "111222333", "username": "OwnerUser"}
        session_id = await auth_mgr.create_session(owner_user, {"access_token": "tok_owner", "expires_in": 3600})
        headers = {"Cookie": f"syncink_session={session_id}"}

        bot = self.app["bot"]
        guild = bot.get_guild(999111222)
        orig_vc = guild.voice_client
        orig_channels = getattr(guild, "voice_channels", [])
        orig_get_cog = bot.get_cog

        mock_vc = MagicMock()
        mock_vc.is_connected.return_value = True
        mock_vc.is_playing.return_value = True
        mock_vc.is_paused.return_value = False
        mock_vc.channel = SimpleNamespace(id=777, name="Music", members=[])

        mock_music_cog = MagicMock()
        mock_music_cog.play_track = AsyncMock(return_value=True)

        guild.voice_client = mock_vc
        guild.voice_channels = [SimpleNamespace(id=777, name="Music", members=[])]
        bot.get_cog = lambda name: mock_music_cog if name == "Music" else None

        service = MusicService.get_instance()
        fake_track = Track(
            title="Maahi Ve Highway",
            clean_title="Maahi Ve Highway",
            author="A.R. Rahman",
            duration=240,
            url="https://youtube.com/watch?v=abc123",
            stream_url="https://stream.example.com/abc123.opus",
            thumbnail="https://img.example.com/art.jpg",
            platform="youtube",
            requested_by=SimpleNamespace(id=111222333, display_name="OwnerUser"),
        )

        try:
            # 1. Play succeeds and returns clean JSON with message (no NameError: asyncio)
            with patch.object(service, "search_and_extract", new=AsyncMock(return_value=[fake_track])), \
                 patch.object(DashboardAPI, "_send_discord_player_card", new=AsyncMock()):
                resp = await self.client.request(
                    "POST",
                    "/api/servers/999111222/control",
                    headers=headers,
                    json={"action": "play", "query": "Maahi Ve Highway"},
                )
                self.assertEqual(resp.status, 200)
                self.assertIn("application/json", resp.headers.get("Content-Type", ""))
                data = await resp.json()
                self.assertTrue(data["success"])
                self.assertEqual(data.get("message"), 'Playing "Maahi Ve Highway" on Discord')
                mock_music_cog.play_track.assert_awaited_once()

                # Simulate current track active -> 2nd play queues instead of overwriting
                service.get_queue(999111222).current_track = fake_track
                resp_q = await self.client.request(
                    "POST",
                    "/api/servers/999111222/control",
                    headers=headers,
                    json={"action": "play", "query": "Maahi Ve Highway"},
                )
                self.assertEqual(resp_q.status, 200)
                q_data = await resp_q.json()
                self.assertEqual(q_data.get("message"), 'Added "Maahi Ve Highway" to queue')

            # 2. No voice channel -> returns 400 clean JSON error (not fake 200)
            service.queues.pop(999111222, None)
            guild.voice_client = None
            guild.voice_channels = []
            with patch.object(service, "search_and_extract", new=AsyncMock(return_value=[fake_track])):
                resp_no_vc = await self.client.request(
                    "POST",
                    "/api/servers/999111222/control",
                    headers=headers,
                    json={"action": "play", "query": "Maahi Ve Highway"},
                )
                self.assertEqual(resp_no_vc.status, 400)
                self.assertIn("application/json", resp_no_vc.headers.get("Content-Type", ""))
                no_vc_data = await resp_no_vc.json()
                self.assertIn("voice channel", no_vc_data["error"].lower())

            # 3. Unknown /api/ route & unhandled API error return clean JSON (never HTML)
            resp_404 = await self.client.request("GET", "/api/does_not_exist")
            self.assertEqual(resp_404.status, 404)
            self.assertIn("application/json", resp_404.headers.get("Content-Type", ""))
            err_404 = await resp_404.json()
            self.assertTrue(err_404.get("error"))

            with patch.object(service, "get_queue", side_effect=RuntimeError("simulated crash")):
                resp_500 = await self.client.request(
                    "POST",
                    "/api/radio/tune",
                    headers=headers,
                    json={"guild_id": 999111222, "url": "https://stream.example.com/live.mp3", "station_name": "TestFM"},
                )
                self.assertEqual(resp_500.status, 500)
                self.assertIn("application/json", resp_500.headers.get("Content-Type", ""))
                err_500 = await resp_500.json()
                self.assertEqual(err_500.get("error"), "Something went wrong on the server. Please try again.")

            # 4. Verify frontend spam-free wrapped toast & error sanitizer assets
            js_text = await (await self.client.request("GET", "/static/app.js")).text()
            self.assertIn("function formatDashboardError", js_text)
            self.assertIn("async function readApiPayload", js_text)
            self.assertIn("_toastCooldowns", js_text)
            self.assertNotIn("showToast('Failed to execute command: ' + err", js_text)
            css_text = await (await self.client.request("GET", "/static/style.css")).text()
            self.assertIn(".toast.toast-error", css_text)
        finally:
            guild.voice_client = orig_vc
            guild.voice_channels = orig_channels
            bot.get_cog = orig_get_cog
            service.queues.pop(999111222, None)
            await auth_mgr.destroy_session(session_id)

    async def test_frame_exact_audio_clock_and_official_search(self):
        """Verifies 20ms PCM frame timing, pause/repeat reset tokens, official audio scoring, and lyrics-filtered search."""
        import threading
        import time
        from types import SimpleNamespace
        from unittest.mock import patch
        from services.music_service import MusicService, BufferedAudioSource, Track
        from services.web.websocket import DashboardWebSocketManager

        # 1. BufferedAudioSource counts ONLY real decoded PCM frames (20ms/frame), immune to startup silence & underruns
        pause_feed_evt = threading.Event()
        class _DummyPCM:
            def __init__(self):
                self.n = 0
            def read(self):
                if self.n < 5:
                    self.n += 1
                    return b"\x01" * 3840
                pause_feed_evt.wait(timeout=2.0)
                return b""
            def cleanup(self):
                pause_feed_evt.set()

        first_hits = []
        src = BufferedAudioSource(_DummyPCM(), buffer_size=5, on_first_frame=lambda: first_hits.append(True))
        service = MusicService.get_instance()
        q = service.get_queue(999111222)
        try:
            q.current_track = Track(
                title="Test Track",
                clean_title="Test Track",
                author="Test Artist",
                duration=200,
                url="https://youtube.com/watch?v=test",
                stream_url="https://stream.example.com/test",
                thumbnail=None,
                platform="youtube",
                requested_by=SimpleNamespace(id=1, display_name="User"),
            )
            q.active_audio_source = src
            q.seek_offset = 0.0
            q.playback_token = 4

            # Wait briefly for background reader to prebuffer frames, position MUST still be 0.0 before read()
            for _ in range(30):
                if src._buffer.qsize() >= 3:
                    break
                await asyncio.sleep(0.01)
            self.assertFalse(src.audio_started)
            self.assertEqual(q.get_playback_time_exact(), 0.0)

            for _ in range(5):
                pkt = src.read()
                self.assertEqual(len(pkt), 3840)
            self.assertTrue(src.audio_started)
            self.assertEqual(len(first_hits), 1)
            self.assertEqual(src.real_frames_read, 5)
            self.assertAlmostEqual(q.get_playback_time_exact(), 0.10, places=2)

            # Empty buffer underrun returns silence WITHOUT incrementing real_frames_read
            while not src._buffer.empty():
                try:
                    src._buffer.get_nowait()
                except Exception:
                    break
            src._finished = False
            underrun_pkt = src.read()
            self.assertEqual(underrun_pkt, b"\x00" * 3840)
            self.assertEqual(src.real_frames_read, 5)

            snap = DashboardWebSocketManager.get_instance().serialize_guild_playback(999111222, self.app["bot"])
            self.assertEqual(snap["playback_token"], 4)
            self.assertTrue(snap["audio_started"])

            # Verify paused state preserves exact PCM frame position without advancing
            guild = self.app["bot"].get_guild(999111222)
            orig_vc = guild.voice_client
            pause_vc = MagicMock()
            pause_vc.is_connected.return_value = True
            pause_vc.is_playing.return_value = False
            pause_vc.is_paused.return_value = True
            pause_vc.channel = None
            guild.voice_client = pause_vc
            try:
                paused_snap = DashboardWebSocketManager.get_instance().serialize_guild_playback(999111222, self.app["bot"])
                self.assertTrue(paused_snap["is_paused"])
                self.assertFalse(paused_snap["is_playing"])
                self.assertAlmostEqual(paused_snap["position"], 0.10, places=2)
            finally:
                guild.voice_client = orig_vc
        finally:
            src.cleanup()
            service.queues.pop(999111222, None)

        # 2. Official studio audio candidate scorer rejects jukeboxes/trailers and prefers Topic/VEVO exact duration
        score_jukebox = MusicService._score_official_candidate(
            {"title": "Arijit Singh Nonstop Jukebox Songs 2022", "channel": "RandomMix", "duration": 5468},
            "Kesariya Arijit Singh",
            expected_duration=268,
        )
        score_short_teaser = MusicService._score_official_candidate(
            {"title": "Kesariya Official Music Video", "channel": "SonyMusicIndiaVEVO", "duration": 173},
            "Kesariya Arijit Singh",
            expected_duration=268,
        )
        score_official_master = MusicService._score_official_candidate(
            {"title": "Kesariya (Official Audio)", "channel": "Arijit Singh - Topic", "duration": 268},
            "Kesariya Arijit Singh",
            expected_duration=268,
        )
        self.assertLess(score_jukebox, -1000)
        self.assertGreater(score_official_master, score_short_teaser)

        # 3. Search suggestions exclude raw YouTube junk & tracks without lyrics when lyrics-backed official matches exist
        class _FakeResp:
            def __init__(self, payload):
                self.status = 200
                self._payload = payload
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            async def json(self, **kwargs):
                return self._payload

        class _FakeSession:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                return False
            def get(self, url, **kwargs):
                if "suggestqueries.google.com" in url:
                    return _FakeResp(["kesar", ["kesariya", "kesariya whatsapp status", "kesariya full movie"]])
                if "itunes.apple.com" in url:
                    return _FakeResp({
                        "results": [
                            {
                                "trackName": "Kesariya (From \"Brahmastra\")",
                                "artistName": "Arijit Singh",
                                "trackTimeMillis": 268000,
                                "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/100x100bb.jpg",
                            },
                            {
                                "trackName": "Kesariya Karaoke Instrumental Cover",
                                "artistName": "Karaoke Studio",
                                "trackTimeMillis": 260000,
                                "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/100x100bb.jpg",
                            },
                            {
                                "trackName": "Kesariya Unsynced Track",
                                "artistName": "Obscure Artist",
                                "trackTimeMillis": 210000,
                                "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/100x100bb.jpg",
                            },
                        ]
                    })
                if "lrclib.net/api/search" in url:
                    return _FakeResp([
                        {
                            "trackName": "Kesariya",
                            "artistName": "Arijit Singh",
                            "duration": 268,
                            "instrumental": False,
                            "syncedLyrics": "[00:12.00] Mujhko itna bataye koi\n[00:16.50] Kaise tujhse dil na lagaye koi",
                            "plainLyrics": "Mujhko itna bataye koi",
                        }
                    ])
                return _FakeResp({})

        with patch("aiohttp.ClientSession", _FakeSession):
            r_sug = await self.client.request("GET", "/api/search/suggestions?q=kesar")
            self.assertEqual(r_sug.status, 200)
            sug_data = await r_sug.json()
            items = sug_data.get("suggestions", [])
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["title"], "Kesariya")
            self.assertEqual(items[0]["artist"], "Arijit Singh")
            self.assertTrue(items[0]["official"])
            self.assertTrue(items[0]["has_lyrics"])
            self.assertTrue(items[0]["lyrics_synced"])
            self.assertIn("600x600bb", items[0]["thumbnail"])

        # 4. Verify unified single-clock & official-music search hooks in static/app.js
        js_text = await (await self.client.request("GET", "/static/app.js")).text()
        self.assertIn("function syncPlaybackClockFromState", js_text)
        self.assertIn("function applyPlaybackTick", js_text)
        self.assertIn("playback_tick", js_text)
        self.assertIn("prefer_official_music", js_text)
        self.assertNotIn("state.playback.position += 1;", js_text)


if __name__ == "__main__":
    unittest.main()
