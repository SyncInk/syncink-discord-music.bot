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
        mock_bot.guilds = []
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


if __name__ == "__main__":
    unittest.main()
