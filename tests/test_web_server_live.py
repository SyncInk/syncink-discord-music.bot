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


if __name__ == "__main__":
    unittest.main()
