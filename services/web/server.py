import os
import time
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
        self.app["_start_time"] = time.time()
        self.runner: Optional[aiohttp.web.AppRunner] = None
        self.site: Optional[aiohttp.web.TCPSite] = None
        self._setup_routes()

    def set_bot(self, bot: Any):
        self.app["bot"] = bot

    def _setup_routes(self):
        def _route(method: str, path: str, handler: Any):
            m = method.upper()
            if m == "GET":
                self.app.router.add_get(path, handler)
                self.app.router.add_get(f"/dashboard/radio{path}", handler)
            elif m == "POST":
                self.app.router.add_post(path, handler)
                self.app.router.add_post(f"/dashboard/radio{path}", handler)
            elif m == "DELETE":
                self.app.router.add_delete(path, handler)
                self.app.router.add_delete(f"/dashboard/radio{path}", handler)
            else:
                self.app.router.add_route(m, path, handler)
                self.app.router.add_route(m, f"/dashboard/radio{path}", handler)

        # 1. Real-Time WebSocket Gateway
        _route("GET", "/ws", DashboardWebSocketManager.get_instance().handle_ws)

        # 2. Discord OAuth2 & User Preferences Endpoints
        _route("GET", "/api/auth/discord/login", DashboardAPI.handle_login)
        _route("GET", "/api/auth/discord/callback", DashboardAPI.handle_oauth_callback)
        _route("GET", "/api/auth/me", DashboardAPI.handle_me)
        _route("GET", "/api/user/me", DashboardAPI.handle_me)
        _route("POST", "/api/auth/logout", DashboardAPI.handle_logout)
        _route("POST", "/api/auth/demo", DashboardAPI.handle_demo_auth)
        _route("GET", "/api/user/preferences", DashboardAPI.handle_get_preferences)
        _route("POST", "/api/user/preferences", DashboardAPI.handle_update_preferences)

        # 3. Servers & Playback Control API
        _route("GET", "/api/servers", DashboardAPI.handle_get_servers)
        _route("GET", "/api/servers/{guild_id}", DashboardAPI.handle_get_server_detail)
        _route("POST", "/api/servers/{guild_id}/control", DashboardAPI.handle_server_control)
        _route("GET", "/api/servers/{guild_id}/settings", DashboardAPI.handle_get_server_settings)
        _route("POST", "/api/servers/{guild_id}/settings", DashboardAPI.handle_update_server_settings)

        # 4. Radio Directory API
        _route("GET", "/api/radio/countries", DashboardAPI.handle_get_radio_countries)
        _route("GET", "/api/radio/stations", DashboardAPI.handle_get_radio_stations)
        _route("GET", "/api/radio/popular", DashboardAPI.handle_get_popular_radio)
        _route("GET", "/api/radio/trending", DashboardAPI.handle_get_trending_radio)
        _route("GET", "/api/radio/genres", DashboardAPI.handle_get_radio_genres)
        _route("POST", "/api/radio/tune", DashboardAPI.handle_tune_radio)

        # 5. Audia AI Engine API
        _route("GET", "/api/audia/profile", DashboardAPI.handle_get_audia_profile)
        _route("GET", "/api/audia/recommendations", DashboardAPI.handle_get_audia_recommendations)
        _route("POST", "/api/audia/settings", DashboardAPI.handle_update_audia_settings)
        _route("POST", "/api/audia/feedback", DashboardAPI.handle_audia_feedback)

        # 6. Library, Playlists & Analytics API
        _route("GET", "/api/library/favorites", DashboardAPI.handle_get_favorites)
        _route("POST", "/api/library/favorites", DashboardAPI.handle_add_favorite)
        _route("DELETE", "/api/library/favorites/{id}", DashboardAPI.handle_remove_favorite)
        _route("GET", "/api/playlists", DashboardAPI.handle_get_playlists)
        _route("POST", "/api/playlists", DashboardAPI.handle_create_playlist)
        _route("POST", "/api/playlists/import", DashboardAPI.handle_import_playlist)
        _route("POST", "/api/user/playlists/import", DashboardAPI.handle_import_playlist)
        _route("DELETE", "/api/playlists/{id}", DashboardAPI.handle_delete_playlist)
        _route("GET", "/api/playlists/{id}/tracks", DashboardAPI.handle_get_playlist_tracks)
        _route("POST", "/api/playlists/{id}/tracks", DashboardAPI.handle_add_playlist_track)
        _route("POST", "/api/playlists/{id}/play", DashboardAPI.handle_play_playlist)
        _route("DELETE", "/api/playlists/{id}/tracks/{track_id}", DashboardAPI.handle_remove_playlist_track)
        _route("GET", "/api/search/suggestions", DashboardAPI.handle_search_suggestions)
        _route("GET", "/api/lyrics", DashboardAPI.handle_get_lyrics)
        _route("GET", "/api/history", DashboardAPI.handle_get_history)
        _route("DELETE", "/api/history/{id}", DashboardAPI.handle_delete_history_item)
        _route("POST", "/api/history/clear", DashboardAPI.handle_clear_history)
        _route("GET", "/api/analytics", DashboardAPI.handle_get_analytics)
        _route("GET", "/api/admin/status", DashboardAPI.handle_admin_status)

        # 6b. Live Telemetry & Bot Status API (Public, CORS-enabled)
        _route("GET", "/api/status", DashboardAPI.handle_public_status)
        _route("GET", "/api/bot/uptime", DashboardAPI.handle_public_status)
        _route("GET", "/api/bot/status", DashboardAPI.handle_public_status)

        # 7. Spotify Web API Endpoints & Callbacks
        _route("GET", "/callback", self.handle_spotify_callback)
        _route("GET", "/api/spotify/callback", self.handle_spotify_callback)
        _route("GET", "/spotify/callback", self.handle_spotify_callback)
        _route("GET", "/api/spotify/status", DashboardAPI.handle_spotify_status)
        _route("GET", "/api/spotify/connect", DashboardAPI.handle_spotify_connect)
        _route("POST", "/api/spotify/disconnect", DashboardAPI.handle_spotify_disconnect)
        _route("GET", "/api/spotify/playlists", DashboardAPI.handle_spotify_playlists)
        _route("POST", "/api/spotify/playlists/add", DashboardAPI.handle_spotify_add_playlist)
        _route("DELETE", "/api/spotify/playlists/{id}", DashboardAPI.handle_spotify_remove_playlist)
        _route("GET", "/health", self.handle_health)

        # 7b. Legal, Documentation, FAQ & Real-Time Status Routes
        _route("GET", "/privacy", self.handle_privacy)
        _route("GET", "/privacy.html", self.handle_privacy)
        _route("GET", "/terms", self.handle_terms)
        _route("GET", "/terms.html", self.handle_terms)
        _route("GET", "/terms-of-use", self.handle_terms)
        _route("GET", "/guide", self.handle_guide)
        _route("GET", "/guide.html", self.handle_guide)
        _route("GET", "/setup", self.handle_guide)
        _route("GET", "/setup.html", self.handle_guide)
        _route("GET", "/commands", self.handle_guide)
        _route("GET", "/commands.html", self.handle_guide)
        _route("GET", "/faq", self.handle_faq)
        _route("GET", "/faq.html", self.handle_faq)
        _route("GET", "/status", self.handle_status)
        _route("GET", "/status.html", self.handle_status)

        # 8. Static Assets (Both root and mounted subpath)
        static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static")
        os.makedirs(static_dir, exist_ok=True)
        self.app.router.add_static("/static", static_dir, name="static")
        self.app.router.add_static("/dashboard/radio/static", static_dir, name="static_subpath")

        # 9. SPA Routing: Supports both / and /dashboard/radio/
        self.app.router.add_get("/dashboard/radio", self.handle_dashboard_redirect)
        self.app.router.add_get("/dashboard/radio/", self.handle_index)

        spa_routes = ["/", "/overview", "/radio", "/audia", "/library", "/history", "/analytics", "/servers", "/admin"]
        for r in spa_routes:
            self.app.router.add_get(r, self.handle_index)
            if r != "/":
                self.app.router.add_get(f"/dashboard/radio{r}", self.handle_index)
                self.app.router.add_get(f"/dashboard/radio{r}/", self.handle_index)

    async def handle_dashboard_redirect(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        raise aiohttp.web.HTTPFound("/dashboard/radio/")

    async def handle_page(self, filename: str) -> aiohttp.web.Response:
        static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static")
        page_file = os.path.join(static_dir, filename)
        if os.path.isfile(page_file):
            return aiohttp.web.FileResponse(page_file)
        return aiohttp.web.Response(text=f"<h1>{filename} not found</h1>", content_type="text/html", status=404)

    async def handle_privacy(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        return await self.handle_page("privacy.html")

    async def handle_terms(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        return await self.handle_page("terms.html")

    async def handle_guide(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        return await self.handle_page("guide.html")

    async def handle_faq(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        return await self.handle_page("faq.html")

    async def handle_status(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        return await self.handle_page("status.html")

    async def handle_index(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        host = (request.headers.get("X-Forwarded-Host") or request.host or "").lower()
        if host.startswith("privacy."):
            return await self.handle_privacy(request)
        if host.startswith("terms."):
            return await self.handle_terms(request)
        if host.startswith("guide.") or host.startswith("setup.") or host.startswith("commands."):
            return await self.handle_guide(request)
        if host.startswith("faq."):
            return await self.handle_faq(request)
        if host.startswith("status."):
            return await self.handle_status(request)

        static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "static")
        index_file = os.path.join(static_dir, "index.html")
        if os.path.isfile(index_file):
            return aiohttp.web.FileResponse(index_file)
        return aiohttp.web.Response(text="<h1>SyncInk Radio Dashboard is initializing...</h1>", content_type="text/html")

    async def handle_spotify_callback(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        code = request.query.get("code")
        state = request.query.get("state")
        error = request.query.get("error")

        is_subpath = (
            request.path.startswith("/dashboard/radio")
            or request.headers.get("X-Forwarded-Prefix") == "/dashboard/radio"
            or "dashboard/radio" in str(request.headers.get("Referer", ""))
        )
        # In production on syncink.site, the dashboard is exclusively mounted under /dashboard/radio
        is_production = "syncink.site" in str(request.host).lower() or "syncink.site" in str(request.headers.get("X-Forwarded-Host", "")).lower()
        base_prefix = "/dashboard/radio" if (is_subpath or is_production) else ""

        if error:
            if state:
                row = await db.fetchrow("SELECT return_to FROM spotify_oauth_states WHERE state = $1;", state)
                if row and row.get("return_to") == "dashboard":
                    raise aiohttp.web.HTTPFound(f"{base_prefix}/#library?spotify_error=" + aiohttp.helpers.quote(error, safe=""))
            html = CALLBACK_HTML_ERROR.replace("{error_message}", f"Spotify authorization was canceled or failed: {error}")
            return aiohttp.web.Response(text=html, content_type="text/html", status=400)

        if not code or not state:
            html = CALLBACK_HTML_ERROR.replace("{error_message}", "Invalid OAuth callback request. Missing 'code' or 'state' parameters.")
            return aiohttp.web.Response(text=html, content_type="text/html", status=400)

        auth_mgr = SpotifyUserAuthManager.get_instance()
        user_auth, err_detail = await auth_mgr.handle_callback_detailed(code, state)

        if not user_auth:
            err_msg = err_detail or "OAuth verification failed or your session expired. Please type <code>/spotify connect</code> in Discord to try again."
            html = CALLBACK_HTML_ERROR.replace("{error_message}", err_msg)
            return aiohttp.web.Response(text=html, content_type="text/html", status=403)

        if getattr(user_auth, "return_to", "discord") == "dashboard":
            raise aiohttp.web.HTTPFound(f"{base_prefix}/#library?spotify_connected=true")

        html = CALLBACK_HTML_SUCCESS.replace("{display_name}", user_auth.display_name or "Spotify User")
        return aiohttp.web.Response(text=html, content_type="text/html", status=200)

    async def handle_health(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        return aiohttp.web.json_response({"status": "ok", "service": "SyncInk Radio Unified Platform", "version": "2.5.0"})

    async def handle_spotify_status(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        return await DashboardAPI.handle_spotify_status(request)

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
