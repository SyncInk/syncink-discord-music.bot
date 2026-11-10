import asyncio
import os
import aiohttp.web
from typing import Optional
from utils.logger import log
from services.spotify.auth import SpotifyUserAuthManager

# HTML Template conforming to SyncInk Design System (Cyber Violet, Glassmorphic, Responsive)
CALLBACK_HTML_SUCCESS = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SyncInk Radio • Spotify Connected</title>
  <link rel="icon" href="https://files.catbox.moe/74l9su.png" type="image/png">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; }
    body {
      background: radial-gradient(circle at 50% 20%, #1e1035 0%, #0d0614 100%);
      color: #ffffff;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .card {
      background: rgba(26, 16, 43, 0.75);
      border: 1px solid rgba(123, 44, 191, 0.4);
      backdrop-filter: blur(20px);
      -webkit-backdrop-filter: blur(20px);
      border-radius: 24px;
      padding: 48px 36px;
      max-width: 480px;
      width: 100%;
      text-align: center;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5), 0 0 40px rgba(123, 44, 191, 0.2);
      animation: floatIn 0.5s ease-out;
    }
    @keyframes floatIn {
      from { opacity: 0; transform: translateY(20px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .icon-container {
      width: 80px;
      height: 80px;
      margin: 0 auto 24px;
      border-radius: 50%;
      background: linear-gradient(135deg, #1db954 0%, #108035 100%);
      display: flex;
      align-items: center;
      justify-content: center;
      box-shadow: 0 8px 24px rgba(29, 185, 84, 0.35);
    }
    .icon-container svg { width: 44px; height: 44px; fill: #ffffff; }
    h1 { font-size: 26px; font-weight: 700; margin-bottom: 12px; letter-spacing: -0.5px; }
    .highlight { color: #1db954; }
    p { font-size: 15px; color: #bcaaa4; line-height: 1.6; margin-bottom: 24px; }
    .user-pill {
      display: inline-flex;
      align-items: center;
      background: rgba(123, 44, 191, 0.25);
      border: 1px solid rgba(123, 44, 191, 0.5);
      padding: 8px 18px;
      border-radius: 999px;
      font-size: 14px;
      font-weight: 600;
      color: #e0aaff;
      margin-bottom: 28px;
    }
    .btn {
      display: block;
      width: 100%;
      background: linear-gradient(135deg, #7b2cbf 0%, #9d4edd 100%);
      color: #ffffff;
      text-decoration: none;
      font-weight: 600;
      padding: 14px 20px;
      border-radius: 14px;
      font-size: 15px;
      transition: all 0.2s ease;
      border: none;
      cursor: pointer;
    }
    .btn:hover {
      box-shadow: 0 6px 20px rgba(123, 44, 191, 0.4);
      transform: translateY(-2px);
    }
    .footer { margin-top: 24px; font-size: 12px; color: #7b2cbf; opacity: 0.8; }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon-container">
      <svg viewBox="0 0 24 24">
        <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z"/>
      </svg>
    </div>
    <h1>Spotify <span class="highlight">Connected</span></h1>
    <p>Your Spotify account is now linked to SyncInk Radio. You can now control personal playlists and access tailored AI DJ recommendations.</p>
    <div class="user-pill">Connected as: {display_name}</div>
    <button class="btn" onclick="window.close();">Return to Discord</button>
    <div class="footer">SyncInk Radio Platform • Protected with PKCE & Token Encryption</div>
  </div>
</body>
</html>
"""

CALLBACK_HTML_ERROR = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>SyncInk Radio • Connection Failed</title>
  <link rel="icon" href="https://files.catbox.moe/74l9su.png" type="image/png">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
    body {
      background: radial-gradient(circle at 50% 20%, #29101d 0%, #0d0614 100%);
      color: #ffffff;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .card {
      background: rgba(35, 16, 26, 0.75);
      border: 1px solid rgba(237, 66, 69, 0.4);
      backdrop-filter: blur(20px);
      border-radius: 24px;
      padding: 48px 36px;
      max-width: 480px;
      width: 100%;
      text-align: center;
      box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
    }
    .icon-container {
      width: 80px;
      height: 80px;
      margin: 0 auto 24px;
      border-radius: 50%;
      background: linear-gradient(135deg, #ed4245 0%, #a82023 100%);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 36px;
    }
    h1 { font-size: 24px; font-weight: 700; margin-bottom: 12px; }
    p { font-size: 15px; color: #d0c0c0; line-height: 1.6; margin-bottom: 24px; }
    .btn {
      display: block;
      width: 100%;
      background: #ed4245;
      color: #ffffff;
      text-decoration: none;
      font-weight: 600;
      padding: 14px 20px;
      border-radius: 14px;
      font-size: 15px;
      border: none;
      cursor: pointer;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon-container">⚠️</div>
    <h1>Connection Failed</h1>
    <p>{error_message}</p>
    <button class="btn" onclick="window.close();">Close Window</button>
  </div>
</body>
</html>
"""

class SpotifyWebServer:
    """
    Embedded lightweight web server running on an asyncio background task
    to receive OAuth callbacks and provide health/status endpoints.
    """
    def __init__(self, port: int = 8888, host: str = "0.0.0.0"):
        self.port = port
        self.host = host
        self.app = aiohttp.web.Application()
        self.runner: Optional[aiohttp.web.AppRunner] = None
        self.site: Optional[aiohttp.web.TCPSite] = None
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/callback", self.handle_callback)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/api/spotify/status", self.handle_api_status)

    async def handle_callback(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        code = request.query.get("code")
        state = request.query.get("state")
        error = request.query.get("error")

        if error:
            log.warning(f"[Spotify Web Server] User denied access or error occurred: {error}")
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
        return aiohttp.web.json_response({"status": "ok", "service": "SyncInk Radio Spotify Service"})

    async def handle_api_status(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
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
            log.info(f"[Spotify Web Server] OAuth callback server listening on http://{self.host}:{self.port}/callback")
        except Exception as e:
            log.warning(f"[Spotify Web Server] Could not start OAuth callback server on port {self.port}: {e}")

    async def stop(self):
        if self.runner:
            try:
                await self.runner.cleanup()
                log.info("[Spotify Web Server] Server stopped cleanly.")
            except Exception:
                pass

_server_instance: Optional[SpotifyWebServer] = None

async def start_spotify_web_server():
    from services.web.server import start_web_server
    await start_web_server()

async def stop_spotify_web_server():
    from services.web.server import stop_web_server
    await stop_web_server()
