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
        self.assertIn("Audia AI", text)

        resp_css = await self.client.request("GET", "/static/style.css")
        self.assertEqual(resp_css.status, 200)
        css_text = await resp_css.text()
        self.assertIn("#101014", css_text)

        resp_js = await self.client.request("GET", "/static/app.js")
        self.assertEqual(resp_js.status, 200)

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


if __name__ == "__main__":
    unittest.main()
