import os
import aiohttp.web
from typing import Optional, Any
from utils.logger import log
from services.web.auth import DashboardAuthManager
from services.web.websocket import DashboardWebSocketManager
from services.web.api import DashboardAPI
from services.spotify.web_server import (
    CALLBACK_HTML_SUCCESS,
    CALLBACK_HTML_ERROR,
    SpotifyUserAuthManager
)

class UnifiedWebServer:
    """
    Unified high-performance AsyncIO Web Server for SyncInk Radio.
    Serves:
    - Production Single-Page Dashboard (Tailwind, Lucide, Cyber Violet design)
    - Discord OAuth2 Login & Callback
    - Full REST API (Servers, Controls, Audia AI, Radio Directory, Library, Analytics)
    - Real-time WebSockets (/ws) with 1-second state synchronization
    - Spotify Web API OAuth Callback (/callback) & Health checks
    """
    def __init__(self, port: int = 8888, host: str = "0.0.0.0", bot: Optional[Any] = None):
        self.port = port
        self.host = host
        self.app = aiohttp.web.Application()
        self.app["bot"] = bot
        self.runner: Optional[aiohttp.web.AppRunner] = None
        self.site: Optional[aiohttp.web.TCPSite] = None
        self._setup_routes()

    def set_bot(self, bot: Any):
        self.app["bot"] = bot

    def _setup_routes(self):
        # 1. Real-Time WebSocket Gateway
        self.app.router.add_get("/ws", DashboardWebSocketManager.get_instance().handle_ws)

        # 2. Discord OAuth2 Endpoints
        self.app.router.add_get("/api/auth/discord/login", DashboardAPI.handle_login)
        self.app.router.add_get("/api/auth/discord/callback", DashboardAPI.handle_oauth_callback)
        self.app.router.add_get("/api/auth/me", DashboardAPI.handle_me)
        self.app.router.add_post("/api/auth/logout", DashboardAPI.handle_logout)

        # 3. Servers & Playback Control API
        self.app.router.add_get("/api/servers", DashboardAPI.handle_get_servers)
        self.app.router.add_get("/api/servers/{guild_id}", DashboardAPI.handle_get_server_detail)
        self.app.router.add_post("/api/servers/{guild_id}/control", DashboardAPI.handle_server_control)
        self.app.router.add_get("/api/servers/{guild_id}/settings", DashboardAPI.handle_get_server_settings)
        self.app.router.add_post("/api/servers/{guild_id}/settings", DashboardAPI.handle_update_server_settings)

        # 4. Radio Directory API
        self.app.router.add_get("/api/radio/countries", DashboardAPI.handle_get_radio_countries)
        self.app.router.add_get("/api/radio/stations", DashboardAPI.handle_get_radio_stations)
        self.app.router.add_post("/api/radio/tune", DashboardAPI.handle_tune_radio)

        # 5. Audia AI (AI DJ) API
        self.app.router.add_get("/api/audia/profile", DashboardAPI.handle_get_audia_profile)
        self.app.router.add_post("/api/audia/settings", DashboardAPI.handle_update_audia_settings)
        self.app.router.add_post("/api/audia/feedback", DashboardAPI.handle_audia_feedback)

        # 6. Library & Analytics API
        self.app.router.add_get("/api/library/favorites", DashboardAPI.handle_get_favorites)
        self.app.router.add_post("/api/library/favorites", DashboardAPI.handle_add_favorite)
        self.app.router.add_delete("/api/library/favorites/{id}", DashboardAPI.handle_remove_favorite)
        self.app.router.add_get("/api/history", DashboardAPI.handle_get_history)
        self.app.router.add_get("/api/analytics", DashboardAPI.handle_get_analytics)
        self.app.router.add_get("/api/admin/status", DashboardAPI.handle_admin_status)

        # 7. Spotify Web API Legacy Endpoints (Kept 100% backward compatible)
        self.app.router.add_get("/callback", self.handle_spotify_callback)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/api/spotify/status", self.handle_spotify_status)

        # 8. Static Assets & SPA Router
        static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static")
        os.makedirs(static_dir, exist_ok=True)
        self.app.router.add_static("/static", static_dir, name="static")

        # Catch-all route to serve Dashboard Single Page App
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/overview", self.handle_index)
        self.app.router.add_get("/radio", self.handle_index)
        self.app.router.add_get("/audia", self.handle_index)
        self.app.router.add_get("/library", self.handle_index)
        self.app.router.add_get("/history", self.handle_index)
        self.app.router.add_get("/analytics", self.handle_index)
        self.app.router.add_get("/servers", self.handle_index)
        self.app.router.add_get("/admin", self.handle_index)

    async def handle_index(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static")
        index_file = os.path.join(static_dir, "index.html")
        if os.path.isfile(index_file):
            return aiohttp.web.FileResponse(index_file)
        return aiohttp.web.Response(text="<h1>SyncInk Radio Dashboard is initializing...</h1>", content_type="text/html")

    async def handle_spotify_callback(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        code = request.query.get("code")
        state = request.query.get("state")
        error = request.query.get("error")

        if error:
            html = CALLBACK_HTML_ERROR.replace("{error_message}", f"Spotify authorization was canceled or failed: {error}")
            return aiohttp.web.Response(text=html, content_type="text/html", status=400)

        if not code or not state:
            html = CALLBACK_HTML_ERROR.replace("{error_message}", "Invalid OAuth callback request. Missing 'code' or 'state' parameters.")
            return aiohttp.web.Response(text=html, content_type="text/html", status=400)

        auth_mgr = SpotifyUserAuthManager.get_instance()
        user_auth = await auth_mgr.handle_callback(code, state)

        if not user_auth:
            html = CALLBACK_HTML_ERROR.replace("{error_message}", "OAuth verification failed or your session expired. Please type <code>/spotify connect</code> in Discord to try again.")
            return aiohttp.web.Response(text=html, content_type="text/html", status=403)

        html = CALLBACK_HTML_SUCCESS.replace("{display_name}", user_auth.display_name or "Spotify User")
        return aiohttp.web.Response(text=html, content_type="text/html", status=200)

    async def handle_health(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        return aiohttp.web.json_response({"status": "ok", "service": "SyncInk Radio Unified Platform", "version": "2.5.0"})

    async def handle_spotify_status(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        user_id_raw = request.query.get("user_id")
        if not user_id_raw or not user_id_raw.isdigit():
            return aiohttp.web.json_response({"error": "Missing or invalid 'user_id' query parameter."}, status=400)

        auth_mgr = SpotifyUserAuthManager.get_instance()
        user_auth = await auth_mgr.get_user_auth(int(user_id_raw))
        if user_auth:
            return aiohttp.web.json_response({
                "connected": True,
                "spotify_user_id": user_auth.spotify_user_id,
                "display_name": user_auth.display_name,
                "email": user_auth.email,
            })
        return aiohttp.web.json_response({"connected": False})

    async def start(self):
        try:
            self.runner = aiohttp.web.AppRunner(self.app)
            await self.runner.setup()
            self.site = aiohttp.web.TCPSite(self.runner, self.host, self.port)
            await self.site.start()
            log.info(f"[Unified Web Server] SyncInk Radio Dashboard listening on http://{self.host}:{self.port} (Public: https://syncink.site)")
        except Exception as e:
            log.warning(f"[Unified Web Server] Could not start web server on port {self.port}: {e}")

    async def stop(self):
        if self.runner:
            try:
                await self.runner.cleanup()
                log.info("[Unified Web Server] Stopped cleanly.")
            except Exception:
                pass

_unified_instance: Optional[UnifiedWebServer] = None

async def start_web_server(bot: Optional[Any] = None) -> UnifiedWebServer:
    global _unified_instance
    if _unified_instance is None:
        port = int(os.getenv("DASHBOARD_PORT") or os.getenv("PORT") or os.getenv("SPOTIFY_CALLBACK_PORT") or 8888)
        _unified_instance = UnifiedWebServer(port=port, bot=bot)
        await _unified_instance.start()
    elif bot:
        _unified_instance.set_bot(bot)
    return _unified_instance

async def stop_web_server():
    global _unified_instance
    if _unified_instance:
        await _unified_instance.stop()
        _unified_instance = None
