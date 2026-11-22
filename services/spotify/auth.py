import asyncio
import base64
import hashlib
import json
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
        "user-read-email",
        "playlist-read-private",
        "playlist-read-collaborative",
        "user-top-read",
        "user-library-read",
    ]

    _instance: Optional['SpotifyUserAuthManager'] = None

    def __init__(self):
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
        self.redirect_uri = self.get_default_redirect_uri()
        self._user_tokens: Dict[int, SpotifyUserAuth] = {}
        self._pending_oauth_states: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def _cleanup_expired_states(self):
        now = time.time()
        expired = [s for s, data in self._pending_oauth_states.items() if now - data.get("created_at", 0) > 900]
        for s in expired:
            self._pending_oauth_states.pop(s, None)

    def get_default_redirect_uri(self) -> str:
        """
        Determines the canonical Spotify OAuth2 redirect URI.
        Safeguards against stale '127.0.0.1' or non-subpath URIs in production environments.
        Since the radio platform is reverse-proxied under '/dashboard/radio', callbacks
        MUST route to https://syncink.site/dashboard/radio/callback to prevent 404 from main site.
        """
        env_uri = os.getenv("SPOTIFY_REDIRECT_URI", "").strip()
        discord_redirect = os.getenv("DISCORD_REDIRECT_URI", "").strip()
        # If running in production (indicated by syncink.site)
        if "syncink.site" in discord_redirect or "syncink.site" in env_uri:
            # If empty, localhost, or unproxied root callback /callback
            if not env_uri or "127.0.0.1" in env_uri or "localhost" in env_uri or env_uri.rstrip("/").endswith("syncink.site/callback"):
                return "https://syncink.site/dashboard/radio/callback"
            return env_uri
        if env_uri:
            return env_uri
        return "https://syncink.site/dashboard/radio/callback"

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

    async def generate_auth_url(
        self,
        discord_user_id: int,
        redirect_uri: Optional[str] = None,
        return_to: str = "discord"
    ) -> Tuple[str, str]:
        """
        Creates an authorization URL with PKCE S256 and stores state in database.
        Returns (authorization_url, state).
        """
        if not self.client_id:
            raise RuntimeError("SPOTIFY_CLIENT_ID is not configured in environment variables.")

        effective_redirect = (redirect_uri or self.get_default_redirect_uri()).strip()
        state = secrets.token_urlsafe(32)
        code_verifier = self._generate_code_verifier()
        code_challenge = self._generate_code_challenge(code_verifier)

        # Record state in in-memory cache for ultra-reliable CSRF resolution
        self._cleanup_expired_states()
        self._pending_oauth_states[state] = {
            "discord_user_id": discord_user_id,
            "code_verifier": code_verifier,
            "redirect_uri": effective_redirect,
            "return_to": return_to,
            "created_at": time.time(),
        }

        # Store state in DB with TTL (15 minutes), specific redirect_uri and return_to target
        try:
            await db.execute(
                """
                INSERT INTO spotify_oauth_states (state, discord_user_id, code_verifier, redirect_uri, return_to)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (state) DO UPDATE SET
                    discord_user_id = $2,
                    code_verifier = $3,
                    redirect_uri = $4,
                    return_to = $5;
                """,
                state, discord_user_id, code_verifier, effective_redirect, return_to
            )
        except Exception as e:
            log.warning(f"[Spotify Auth] Could not persist oauth state to DB (falling back to memory): {e}")

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": effective_redirect,
            "state": state,
            "scope": " ".join(self.DEFAULT_SCOPES),
            "code_challenge_method": "S256",
            "code_challenge": code_challenge,
        }
        query_string = urllib.parse.urlencode(params)
        auth_url = f"{self.AUTH_ENDPOINT}?{query_string}"
        return auth_url, state

    async def handle_callback_detailed(self, code: str, state: str) -> Tuple[Optional[SpotifyUserAuth], Optional[str]]:
        """
        Validates state token, exchanges code + PKCE verifier for tokens,
        fetches user profile, encrypts refresh token, and stores in database.
        Returns (user_auth, error_message).
        """
        row = None
        try:
            row = await db.fetchrow(
                "SELECT discord_user_id, code_verifier, redirect_uri, return_to FROM spotify_oauth_states WHERE state = $1;",
                state
            )
        except Exception as e:
            log.warning(f"[Spotify Auth] DB lookup failed for state: {e}")

        # Fallback to in-memory pending states if not found or DB error
        mem_state = self._pending_oauth_states.get(state)
        if not row and mem_state:
            # Check 15-minute TTL
            if time.time() - mem_state.get("created_at", 0) <= 900:
                row = mem_state

        if not row:
            log.warning(f"[Spotify Auth] Rejected callback with invalid/expired state: {state}")
            return None, "Authorization session is invalid or expired (15-minute timeout). Please initiate a new connection."

        discord_user_id = int(row["discord_user_id"])
        code_verifier = row["code_verifier"]
        redirect_uri = (row.get("redirect_uri") if isinstance(row, dict) else row["redirect_uri"]) or self.get_default_redirect_uri()
        return_to = (row.get("return_to") if isinstance(row, dict) else row["return_to"]) or "discord"

        # Exchange authorization code for tokens using pure PKCE (RFC 7636).
        # Per Spotify documentation: do NOT send client_secret or Authorization: Basic in PKCE flow.
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            "code_verifier": code_verifier,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        async with aiohttp.ClientSession() as session:
            async with session.post(self.TOKEN_ENDPOINT, data=data, headers=headers) as resp:
                token_data = None
                if resp.status == 200:
                    token_data = await resp.json()
                else:
                    err_text = await resp.text()
                    log.error(f"[Spotify Auth] Pure PKCE token exchange failed HTTP {resp.status}: {err_text}")
                    # If Spotify rejected pure PKCE and client_secret is configured, attempt fallback with Basic Auth header
                    if self.client_secret:
                        log.info("[Spotify Auth] Retrying token exchange with Basic Auth header fallback...")
                        auth_str = f"{self.client_id}:{self.client_secret}".encode("utf-8")
                        fb_headers = {
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Authorization": f"Basic {base64.b64encode(auth_str).decode('ascii')}"
                        }
                        async with session.post(self.TOKEN_ENDPOINT, data=data, headers=fb_headers) as fb_resp:
                            if fb_resp.status == 200:
                                token_data = await fb_resp.json()
                            else:
                                fb_err = await fb_resp.text()
                                log.error(f"[Spotify Auth] Fallback token exchange also failed HTTP {fb_resp.status}: {fb_err}")

                    if not token_data:
                        desc = err_text
                        try:
                            parsed_err = json.loads(err_text)
                            desc = parsed_err.get("error_description") or parsed_err.get("error") or err_text
                        except Exception:
                            pass
                        return None, f"Spotify token exchange failed (HTTP {resp.status}): {desc}"

            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")
            expires_in = int(token_data.get("expires_in", 3600))
            scope = token_data.get("scope", "")

            # Fetch user profile from Spotify (non-blocking fallback if profile permissions or Dev Mode allowlist restricts /v1/me)
            profile_data = {}
            profile_headers = {"Authorization": f"Bearer {access_token}"}
            try:
                async with session.get(self.API_ME_ENDPOINT, headers=profile_headers) as p_resp:
                    if p_resp.status == 200:
                        profile_data = await p_resp.json()
                    else:
                        p_err = await p_resp.text()
                        log.warning(f"[Spotify Auth] Could not fetch profile HTTP {p_resp.status}: {p_err}. Using fallback profile.")
            except Exception as e:
                log.warning(f"[Spotify Auth] Exception fetching Spotify profile: {e}. Using fallback profile.")

        # Delete state token now that token exchange and validation have succeeded
        self._pending_oauth_states.pop(state, None)
        try:
            await db.execute("DELETE FROM spotify_oauth_states WHERE state = $1;", state)
        except Exception:
            pass

        # Resolve real member name for display_name
        discord_username = None
        try:
            u_row = await db.fetchrow("SELECT username, global_name FROM user_sessions WHERE discord_user_id = $1 LIMIT 1;", discord_user_id)
            if u_row:
                discord_username = u_row.get("global_name") or u_row.get("username")
        except Exception:
            pass

        spotify_user_id = profile_data.get("id") or (f"@{discord_username}" if discord_username else f"user_{discord_user_id}")
        display_name = profile_data.get("display_name") or discord_username or "Spotify User"
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
            return_to=return_to,
        )
        self._user_tokens[discord_user_id] = user_auth
        log.info(f"[Spotify Auth] Successfully linked Discord user {discord_user_id} with Spotify user '{display_name}' ({spotify_user_id}).")
        return user_auth, None

    async def handle_callback(self, code: str, state: str) -> Optional[SpotifyUserAuth]:
        """
        Validates state token, exchanges code + PKCE verifier for tokens,
        fetches user profile, encrypts refresh token, and stores in database.
        """
        user_auth, _ = await self.handle_callback_detailed(code, state)
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

        async with aiohttp.ClientSession() as session:
            async with session.post(self.TOKEN_ENDPOINT, data=data, headers=headers) as resp:
                token_data = None
                if resp.status == 200:
                    token_data = await resp.json()
                elif self.client_secret:
                    # Retry with Basic Auth header if required
                    auth_str = f"{self.client_id}:{self.client_secret}".encode("utf-8")
                    fb_headers = {
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Authorization": f"Basic {base64.b64encode(auth_str).decode('ascii')}"
                    }
                    async with session.post(self.TOKEN_ENDPOINT, data=data, headers=fb_headers) as fb_resp:
                        if fb_resp.status == 200:
                            token_data = await fb_resp.json()
                        else:
                            log.warning(f"[Spotify Auth] Token refresh failed HTTP {fb_resp.status} for user {discord_user_id}")
                            return None
                else:
                    log.warning(f"[Spotify Auth] Token refresh failed HTTP {resp.status} for user {discord_user_id}")
                    return None

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

        display_name = row["display_name"]
        spotify_user_id = row["spotify_user_id"]
        # Auto-heal display name if generic 'Spotify User' or raw ID
        if not display_name or display_name in ("Spotify User", "unknown") or display_name.startswith("spotify_"):
            try:
                u_row = await db.fetchrow("SELECT username, global_name FROM user_sessions WHERE discord_user_id = $1 LIMIT 1;", discord_user_id)
                if u_row:
                    real_name = u_row.get("global_name") or u_row.get("username")
                    if real_name:
                        display_name = real_name
                        if spotify_user_id.startswith("spotify_") or spotify_user_id.startswith("user_"):
                            spotify_user_id = f"@{real_name}"
                        await db.execute("UPDATE spotify_users SET display_name = $1, spotify_user_id = $2 WHERE discord_user_id = $3;", display_name, spotify_user_id, discord_user_id)
            except Exception:
                pass

        user_auth = SpotifyUserAuth(
            discord_user_id=discord_user_id,
            spotify_user_id=spotify_user_id,
            display_name=display_name,
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

    async def get_user_playlists(self, discord_user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetches the user's Spotify playlists (including private and collaborative playlists).
        """
        token = await self.get_valid_user_token(discord_user_id)
        if not token:
            return []

        url = f"https://api.spotify.com/v1/me/playlists?limit={min(max(1, limit), 50)}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            timeout = aiohttp.ClientTimeout(total=15, connect=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        if resp.status == 403:
                            log.debug(f"[Spotify Auth] User playlists endpoint returned HTTP 403 (Dev Mode user allowlist required for live private playlist sync).")
                        else:
                            log.warning(f"[Spotify Auth] Failed to fetch playlists for user {discord_user_id}: HTTP {resp.status}")
                        items = []
                    else:
                        data = await resp.json()
                        items = data.get("items", [])
        except Exception as e:
            log.error(f"[Spotify Auth] Error fetching user playlists: {e}")
            items = []

        playlists = []
        for p in items:
            if not isinstance(p, dict) or not p.get("id"):
                continue
            images = p.get("images", [])
            img_url = images[0].get("url") if images else "https://files.catbox.moe/74l9su.png"
            playlists.append({
                "id": p["id"],
                "name": p.get("name") or "Untitled Playlist",
                "description": p.get("description") or "",
                "tracks_total": int(p.get("tracks", {}).get("total", 0)),
                "image_url": img_url,
                "url": p.get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{p['id']}"),
                "public": bool(p.get("public", False)),
                "collaborative": bool(p.get("collaborative", False)),
                "owner": p.get("owner", {}).get("display_name") or p.get("owner", {}).get("id") or "Spotify User",
            })

        # If Spotify returned empty or was blocked by Dev Mode (HTTP 403), include user's SyncInk Radio library playlists
        if not playlists:
            try:
                db_playlists = await db.fetch("""
                    SELECT p.id, p.name, p.description, p.is_public,
                           (SELECT COUNT(*) FROM user_playlist_tracks pt WHERE pt.playlist_id = p.id) as total_tracks
                    FROM user_playlists p
                    WHERE p.discord_user_id = $1
                    ORDER BY p.updated_at DESC;
                """, discord_user_id)
                for p in db_playlists:
                    playlists.append({
                        "id": str(p["id"]),
                        "name": p["name"],
                        "description": p.get("description") or "SyncInk Radio Library Playlist",
                        "tracks_total": int(p["total_tracks"] or 0),
                        "image_url": "https://files.catbox.moe/74l9su.png",
                        "url": "https://syncink.site/dashboard/radio/#library",
                        "public": bool(p.get("is_public", True)),
                        "collaborative": False,
                        "owner": "SyncInk Radio",
                    })
            except Exception:
                pass

        return playlists
