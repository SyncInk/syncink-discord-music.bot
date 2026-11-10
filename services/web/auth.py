import os
import secrets
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from database import db
from utils.logger import log

DISCORD_API_BASE = "https://discord.com/api/v10"

class DashboardAuthManager:
    _instance: Optional['DashboardAuthManager'] = None

    def __init__(self):
        self.client_id = os.getenv("DISCORD_CLIENT_ID") or os.getenv("CLIENT_ID") or ""
        self.client_secret = os.getenv("DISCORD_CLIENT_SECRET") or os.getenv("CLIENT_SECRET") or ""
        self.redirect_uri = os.getenv("DISCORD_REDIRECT_URI") or "https://syncink.site/api/auth/discord/callback"

    @classmethod
    def get_instance(cls) -> 'DashboardAuthManager':
        if cls._instance is None:
            cls._instance = DashboardAuthManager()
        return cls._instance

    def get_login_url(self, state: Optional[str] = None) -> str:
        if not state:
            state = secrets.token_urlsafe(24)
        scopes = "identify guilds"
        return (
            f"https://discord.com/oauth2/authorize?client_id={self.client_id}"
            f"&response_type=code&redirect_uri={aiohttp.helpers.quote(self.redirect_uri, safe='')}"
            f"&scope={aiohttp.helpers.quote(scopes, safe='')}&state={state}&prompt=consent"
        )

    async def exchange_code(self, code: str) -> Optional[Dict[str, Any]]:
        """Exchanges authorization code for access and refresh tokens."""
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(f"{DISCORD_API_BASE}/oauth2/token", data=data, headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    err = await resp.text()
                    log.warning(f"[Dashboard Auth] Token exchange failed: {resp.status} - {err[:120]}")
                    return None
        except Exception as e:
            log.error(f"[Dashboard Auth] Token exchange exception: {e}")
            return None

    async def fetch_user(self, access_token: str) -> Optional[Dict[str, Any]]:
        """Fetches the Discord @me user profile."""
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{DISCORD_API_BASE}/users/@me", headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return None
        except Exception as e:
            log.error(f"[Dashboard Auth] Fetch user error: {e}")
            return None

    async def fetch_user_guilds(self, access_token: str) -> List[Dict[str, Any]]:
        """Fetches all guilds the user is a member of."""
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{DISCORD_API_BASE}/users/@me/guilds", headers=headers) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    return []
        except Exception as e:
            log.error(f"[Dashboard Auth] Fetch guilds error: {e}")
            return []

    async def create_session(self, user_data: Dict[str, Any], token_data: Dict[str, Any]) -> str:
        """Stores a new authenticated session in database."""
        session_id = secrets.token_hex(32)
        user_id = int(user_data["id"])
        username = user_data.get("username", "Listener")
        discriminator = user_data.get("discriminator", "0")
        avatar = user_data.get("avatar")
        access_token = token_data.get("access_token", "")
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 604800)
        expires_at = datetime.utcnow() + timedelta(seconds=expires_in)

        query = """
            INSERT INTO user_sessions (session_id, discord_user_id, username, discriminator, avatar, access_token, refresh_token, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        try:
            await db.execute(query, session_id, user_id, username, discriminator, avatar, access_token, refresh_token, expires_at)
        except Exception as e:
            log.error(f"[Dashboard Auth] Error saving user session: {e}")

        return session_id

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves and validates an active user session."""
        if not session_id:
            return None
        query = "SELECT * FROM user_sessions WHERE session_id = $1"
        row = await db.fetchrow(query, session_id)
        if not row:
            return None

        # Check expiration
        expires_at = row.get("expires_at")
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except Exception:
                expires_at = None

        if expires_at and expires_at < datetime.utcnow():
            await self.destroy_session(session_id)
            return None

        return dict(row)

    async def destroy_session(self, session_id: str):
        """Removes a session from database."""
        if session_id:
            await db.execute("DELETE FROM user_sessions WHERE session_id = $1", session_id)
