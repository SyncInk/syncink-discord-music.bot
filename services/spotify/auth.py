import asyncio
import base64
import hashlib
import os
import secrets
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple, Any
import aiohttp

from utils.logger import log
from database import db
from services.spotify.models import SpotifyUserAuth
from services.spotify.crypto import TokenEncryptor

class SpotifyUserAuthManager:
    """
    Handles Spotify User OAuth 2.0 with PKCE and CSRF state token verification.
    Manages secure token storage, refresh lifecycles, and account linking/unlinking.
    """
    AUTH_ENDPOINT = "https://accounts.spotify.com/authorize"
    TOKEN_ENDPOINT = "https://accounts.spotify.com/api/token"
    API_ME_ENDPOINT = "https://api.spotify.com/v1/me"

    DEFAULT_SCOPES = [
        "user-read-private",
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-top-read",
        "user-library-read",
    ]

    _instance: Optional['SpotifyUserAuthManager'] = None

    def __init__(self):
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
        # Default to local 127.0.0.1:8888 or production redirect URI
        self.redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback").strip()
        self._user_tokens: Dict[int, SpotifyUserAuth] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> 'SpotifyUserAuthManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _generate_code_verifier() -> str:
        """Generates a high-entropy cryptographic PKCE code verifier (43-128 chars)."""
        return secrets.token_urlsafe(64)[:96]

    @staticmethod
    def _generate_code_challenge(verifier: str) -> str:
        """Computes the S256 code challenge for PKCE."""
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    async def generate_auth_url(self, discord_user_id: int) -> Tuple[str, str]:
        """
        Creates an authorization URL with PKCE S256 and stores state in database.
        Returns (authorization_url, state).
        """
        if not self.client_id:
            raise RuntimeError("SPOTIFY_CLIENT_ID is not configured in environment variables.")

        state = secrets.token_urlsafe(32)
        code_verifier = self._generate_code_verifier()
        code_challenge = self._generate_code_challenge(code_verifier)

        # Store state in DB with TTL (15 minutes)
        await db.execute(
            """
            INSERT INTO spotify_oauth_states (state, discord_user_id, code_verifier)
            VALUES ($1, $2, $3)
            ON CONFLICT (state) DO UPDATE SET code_verifier = $3;
            """,
            state, discord_user_id, code_verifier
        )

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "state": state,
            "scope": " ".join(self.DEFAULT_SCOPES),
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
        }
        query_string = urllib.parse.urlencode(params)
        auth_url = f"{self.AUTH_ENDPOINT}?{query_string}"
        return auth_url, state

    async def handle_callback(self, code: str, state: str) -> Optional[SpotifyUserAuth]:
        """
        Validates state token, exchanges code + PKCE verifier for tokens,
        fetches user profile, encrypts refresh token, and stores in database.
        """
        row = await db.fetchrow(
            "SELECT discord_user_id, code_verifier FROM spotify_oauth_states WHERE state = $1;",
            state
        )
        if not row:
            log.warning(f"[Spotify Auth] Rejected callback with invalid/expired state: {state}")
            return None

        discord_user_id = int(row["discord_user_id"])
        code_verifier = row["code_verifier"]

        # Consume state immediately (one-time CSRF protection)
        await db.execute("DELETE FROM spotify_oauth_states WHERE state = $1;", state)

        # Exchange authorization code for tokens
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": code_verifier,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        # If client_secret is configured, include Basic Auth header as permitted by Spotify
        if self.client_secret:
            auth_str = f"{self.client_id}:{self.client_secret}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(auth_str).decode('ascii')}"

        async with aiohttp.ClientSession() as session:
            async with session.post(self.TOKEN_ENDPOINT, data=data, headers=headers) as resp:
                if resp.status != 200:
                    err_text = await resp.text()
                    log.error(f"[Spotify Auth] Token exchange failed HTTP {resp.status}: {err_text}")
                    return None
                token_data = await resp.json()

            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            expires_in = int(token_data.get("expires_in", 3600))
            scope = token_data.get("scope", "")

            # Fetch user profile from Spotify
            profile_headers = {"Authorization": f"Bearer {access_token}"}
            async with session.get(self.API_ME_ENDPOINT, headers=profile_headers) as p_resp:
                if p_resp.status != 200:
                    log.error(f"[Spotify Auth] Could not fetch profile HTTP {p_resp.status}")
                    return None
                profile_data = await p_resp.json()

        spotify_user_id = profile_data.get("id") or "unknown"
        display_name = profile_data.get("display_name") or spotify_user_id
        email = profile_data.get("email")

        # Encrypt the refresh token before database storage
        encrypted_rt = TokenEncryptor.encrypt(refresh_token) if refresh_token else ""

        # Store or update in database
        await db.execute(
            """
            INSERT INTO spotify_users (
                discord_user_id, spotify_user_id, display_name, email,
                encrypted_refresh_token, scope, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
            ON CONFLICT (discord_user_id) DO UPDATE SET
                spotify_user_id = $2,
                display_name = $3,
                email = $4,
                encrypted_refresh_token = $5,
                scope = $6,
                updated_at = CURRENT_TIMESTAMP;
            """,
            discord_user_id, spotify_user_id, display_name, email, encrypted_rt, scope
        )

        user_auth = SpotifyUserAuth(
            discord_user_id=discord_user_id,
            spotify_user_id=spotify_user_id,
            display_name=display_name,
            email=email,
            access_token=access_token,
            encrypted_refresh_token=encrypted_rt,
            expires_at=time.time() + expires_in,
            scope=scope,
        )
        self._user_tokens[discord_user_id] = user_auth
        log.info(f"[Spotify Auth] Successfully linked Discord user {discord_user_id} with Spotify user '{display_name}' ({spotify_user_id}).")
        return user_auth

    async def get_valid_user_token(self, discord_user_id: int) -> Optional[str]:
        """
        Retrieves a valid access token for the given Discord user,
        automatically refreshing it using the encrypted refresh token if expired.
        """
        user_auth = await self.get_user_auth(discord_user_id)
        if not user_auth:
            return None

        # Check if current token has at least 60s remaining
        now = time.time()
        if user_auth.access_token and (user_auth.expires_at - now) > 60:
            return user_auth.access_token

        # Refresh token
        refresh_token = TokenEncryptor.decrypt(user_auth.encrypted_refresh_token or "")
        if not refresh_token:
            log.warning(f"[Spotify Auth] Missing or corrupted refresh token for Discord user {discord_user_id}")
            return None

        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.client_id,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if self.client_secret:
            auth_str = f"{self.client_id}:{self.client_secret}".encode("utf-8")
            headers["Authorization"] = f"Basic {base64.b64encode(auth_str).decode('ascii')}"

        async with aiohttp.ClientSession() as session:
            async with session.post(self.TOKEN_ENDPOINT, data=data, headers=headers) as resp:
                if resp.status != 200:
                    log.warning(f"[Spotify Auth] Token refresh failed HTTP {resp.status} for user {discord_user_id}")
                    return None
                token_data = await resp.json()

        new_access = token_data.get("access_token")
        new_refresh = token_data.get("refresh_token")
        expires_in = int(token_data.get("expires_in", 3600))

        user_auth.access_token = new_access
        user_auth.expires_at = time.time() + expires_in

        # Update refresh token if a new one was issued
        if new_refresh:
            user_auth.encrypted_refresh_token = TokenEncryptor.encrypt(new_refresh)
            await db.execute(
                "UPDATE spotify_users SET encrypted_refresh_token = $1, updated_at = CURRENT_TIMESTAMP WHERE discord_user_id = $2;",
                user_auth.encrypted_refresh_token, discord_user_id
            )

        self._user_tokens[discord_user_id] = user_auth
        return new_access

    async def get_user_auth(self, discord_user_id: int) -> Optional[SpotifyUserAuth]:
        """Loads Spotify user auth from memory cache or database."""
        if discord_user_id in self._user_tokens:
            return self._user_tokens[discord_user_id]

        row = await db.fetchrow(
            "SELECT spotify_user_id, display_name, email, encrypted_refresh_token, scope FROM spotify_users WHERE discord_user_id = $1;",
            discord_user_id
        )
        if not row:
            return None

        user_auth = SpotifyUserAuth(
            discord_user_id=discord_user_id,
            spotify_user_id=row["spotify_user_id"],
            display_name=row["display_name"],
            email=row["email"],
            access_token=None,
            encrypted_refresh_token=row["encrypted_refresh_token"],
            expires_at=0.0,
            scope=row["scope"],
        )
        self._user_tokens[discord_user_id] = user_auth
        return user_auth

    async def unlink_user(self, discord_user_id: int) -> bool:
        """Disconnects a user's Spotify account and purges stored tokens."""
        self._user_tokens.pop(discord_user_id, None)
        res = await db.execute("DELETE FROM spotify_users WHERE discord_user_id = $1;", discord_user_id)
        log.info(f"[Spotify Auth] Unlinked Spotify account for Discord user {discord_user_id}.")
        return res != "0"
