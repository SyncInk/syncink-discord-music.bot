import asyncio
import base64
import os
import random
import time
from typing import Dict, List, Optional, Any
import aiohttp

from utils.logger import log
from services.spotify.models import (
    SpotifyTrackMetadata,
    SpotifyAlbumMetadata,
    SpotifyPlaylistMetadata,
    SpotifyArtistMetadata,
)

class SpotifyAPIError(Exception):
    """Custom exception raised when Spotify Web API encounters an unrecoverable error."""
    pass

class SpotifyRateLimitError(SpotifyAPIError):
    pass

class SpotifyClient:
    """
    Official Spotify Web API Client utilizing Client Credentials OAuth Flow.
    Features automatic token caching, pre-expiry renewal, rate-limit backoff with jitter,
    and structured error handling.
    """
    _instance: Optional['SpotifyClient'] = None

    TOKEN_ENDPOINT = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1"

    def __init__(self):
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self._session: Optional[aiohttp.ClientSession] = None

    @classmethod
    def get_instance(cls) -> 'SpotifyClient':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def is_configured(self) -> bool:
        """Returns True if Spotify developer credentials are set."""
        return bool(self.client_id and self.client_secret)

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15, connect=5)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def get_app_token(self, force_refresh: bool = False) -> str:
        """
        Retrieves a valid Spotify Client Credentials access token.
        Automatically renews the token if it is expired or expiring within 60 seconds.
        """
        if not self.is_configured:
            raise SpotifyAPIError("SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET is missing. Please configure them in .env.")

        # Check existing cached token
        now = time.time()
        if not force_refresh and self._access_token and (self._expires_at - now) > 60:
            return self._access_token

        async with self._token_lock:
            # Double check inside lock
            now = time.time()
            if not force_refresh and self._access_token and (self._expires_at - now) > 60:
                return self._access_token

            auth_bytes = f"{self.client_id}:{self.client_secret}".encode("utf-8")
            auth_b64 = base64.b64encode(auth_bytes).decode("ascii")

            headers = {
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/x-www-form-urlencoded",
            }
            data = {"grant_type": "client_credentials"}

            session = self._get_session()
            log.info("[Spotify Client] Requesting fresh Client Credentials token from Spotify...")
            try:
                async with session.post(self.TOKEN_ENDPOINT, headers=headers, data=data) as resp:
                    if resp.status == 200:
                        payload = await resp.json()
                        self._access_token = payload.get("access_token")
                        expires_in = int(payload.get("expires_in", 3600))
                        self._expires_at = time.time() + expires_in
                        log.info(f"[Spotify Client] Successfully acquired Client Credentials token (valid for {expires_in}s).")
                        return self._access_token
                    else:
                        err_body = await resp.text()
                        log.error(f"[Spotify Client] Token request failed HTTP {resp.status}: {err_body}")
                        raise SpotifyAPIError(f"Spotify authentication failed (HTTP {resp.status}): {err_body}")
            except aiohttp.ClientError as ce:
                log.error(f"[Spotify Client] Network connection error requesting token: {ce}")
                raise SpotifyAPIError(f"Network error contacting Spotify accounts service: {ce}")

    async def _request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        retries: int = 3,
        user_token: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Executes an authenticated GET request against the Spotify Web API with
        automatic token renewal and rate limit backoff.
        """
        url = f"{self.API_BASE}/{endpoint.lstrip('/')}"
        session = self._get_session()

        for attempt in range(retries):
            token = user_token if user_token else await self.get_app_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }

            try:
                async with session.get(url, headers=headers, params=params) as resp:
                    if resp.status == 200:
                        return await resp.json()

                    elif resp.status == 429:
                        # Rate limit reached: inspect Retry-After header
                        retry_after = int(resp.headers.get("Retry-After", 1))
                        jitter = random.uniform(0.1, 0.5)
                        backoff = retry_after + jitter
                        log.warning(f"[Spotify Client] Rate limited (HTTP 429). Backing off for {backoff:.2f}s (Attempt {attempt+1}/{retries})")
                        await asyncio.sleep(backoff)
                        continue

                    elif resp.status == 401 and not user_token:
                        # Expired app token: force refresh and retry
                        log.info("[Spotify Client] Received HTTP 401 Unauthorized. Forcing token refresh...")
                        await self.get_app_token(force_refresh=True)
                        continue

                    elif resp.status == 404:
                        log.debug(f"[Spotify Client] Resource not found: {url}")
                        return None

                    elif resp.status in (500, 502, 503, 504):
                        # Server transient error: exponential backoff
                        backoff = (2 ** attempt) + random.uniform(0.1, 0.5)
                        log.warning(f"[Spotify Client] Transient error HTTP {resp.status}. Retrying in {backoff:.2f}s...")
                        await asyncio.sleep(backoff)
                        continue

                    else:
                        err_text = await resp.text()
                        log.warning(f"[Spotify Client] Request failed HTTP {resp.status} for {url}: {err_text}")
                        return None

            except asyncio.TimeoutError:
                log.warning(f"[Spotify Client] Request timeout for {url} (Attempt {attempt+1}/{retries})")
                await asyncio.sleep(1.0)
            except aiohttp.ClientError as ce:
                log.warning(f"[Spotify Client] Network error for {url}: {ce}")
                await asyncio.sleep(1.0)

        log.error(f"[Spotify Client] Exhausted all {retries} retry attempts for {url}.")
        return None

    # ─────────────────────────────────────────────────────────────
    # Resource Metadata Retrievers
    # ─────────────────────────────────────────────────────────────

    async def get_track(self, track_id: str, user_token: Optional[str] = None) -> Optional[SpotifyTrackMetadata]:
        """Fetches metadata for a single Spotify track."""
        data = await self._request(f"tracks/{track_id}", user_token=user_token)
        if not data:
            return None
        return self._parse_track(data)

    async def get_album(self, album_id: str, limit: int = 100, user_token: Optional[str] = None) -> Optional[SpotifyAlbumMetadata]:
        """Fetches metadata and track list for a Spotify album."""
        data = await self._request(f"albums/{album_id}", user_token=user_token)
        if not data:
            return None

        artists = [a.get("name", "") for a in data.get("artists", []) if a.get("name")]
        images = data.get("images", [])
        artwork = images[0].get("url") if images else None
        open_url = data.get("external_urls", {}).get("spotify", f"https://open.spotify.com/album/{album_id}")
        album_name = data.get("name", "Unknown Album")
        release_date = data.get("release_date")
        total_tracks = int(data.get("total_tracks", 0))

        raw_tracks = data.get("tracks", {}).get("items", [])
        parsed_tracks: List[SpotifyTrackMetadata] = []
        for item in raw_tracks[:limit]:
            if not item:
                continue
            item_artists = [a.get("name", "") for a in item.get("artists", []) if a.get("name")]
            parsed_tracks.append(
                SpotifyTrackMetadata(
                    id=item.get("id") or "",
                    name=item.get("name") or "Unknown Track",
                    artists=item_artists or artists,
                    album=album_name,
                    duration_ms=int(item.get("duration_ms", 0)),
                    open_url=item.get("external_urls", {}).get("spotify", ""),
                    artwork_url=artwork,
                    isrc=item.get("external_ids", {}).get("isrc"),
                    explicit=bool(item.get("explicit", False)),
                    preview_url=item.get("preview_url"),
                    release_date=release_date
                )
            )

        return SpotifyAlbumMetadata(
            id=album_id,
            name=album_name,
            artists=artists,
            total_tracks=total_tracks,
            tracks=parsed_tracks,
            open_url=open_url,
            artwork_url=artwork,
            release_date=release_date
        )

    async def get_playlist(self, playlist_id: str, limit: int = 100, user_token: Optional[str] = None) -> Optional[SpotifyPlaylistMetadata]:
        """Fetches metadata and items for a Spotify playlist."""
        data = await self._request(
            f"playlists/{playlist_id}",
            params={"fields": "id,name,description,owner,images,external_urls,tracks.total,tracks.items(track(id,name,artists,album(name,images),duration_ms,external_urls,external_ids,explicit,preview_url))"},
            user_token=user_token
        )
        if not data:
            return None

        playlist_name = data.get("name", "Spotify Playlist")
        owner_name = data.get("owner", {}).get("display_name") or data.get("owner", {}).get("id") or "Spotify User"
        images = data.get("images", [])
        artwork = images[0].get("url") if images else None
        open_url = data.get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{playlist_id}")
        description = data.get("description")

        tracks_container = data.get("tracks", {})
        total_tracks = int(tracks_container.get("total", 0))
        items = tracks_container.get("items", [])

        parsed_tracks: List[SpotifyTrackMetadata] = []
        for item in items[:limit]:
            t = item.get("track") if isinstance(item, dict) else None
            if not t or not t.get("name"):
                continue
            parsed_tracks.append(self._parse_track(t, default_artwork=artwork))

        return SpotifyPlaylistMetadata(
            id=playlist_id,
            name=playlist_name,
            owner_name=owner_name,
            total_tracks=total_tracks,
            tracks=parsed_tracks,
            open_url=open_url,
            artwork_url=artwork,
            description=description
        )

    async def get_artist_top_tracks(self, artist_id: str, market: str = "US", user_token: Optional[str] = None) -> Optional[SpotifyArtistMetadata]:
        """Fetches an artist profile and their top tracks."""
        artist_data = await self._request(f"artists/{artist_id}", user_token=user_token)
        if not artist_data:
            return None

        top_tracks_data = await self._request(f"artists/{artist_id}/top-tracks", params={"market": market}, user_token=user_token)
        raw_tracks = top_tracks_data.get("tracks", []) if top_tracks_data else []

        artist_name = artist_data.get("name", "Artist")
        genres = artist_data.get("genres", [])
        followers = artist_data.get("followers", {}).get("total")
        images = artist_data.get("images", [])
        image_url = images[0].get("url") if images else None
        open_url = artist_data.get("external_urls", {}).get("spotify", f"https://open.spotify.com/artist/{artist_id}")

        top_tracks = [self._parse_track(t) for t in raw_tracks[:10] if t]

        return SpotifyArtistMetadata(
            id=artist_id,
            name=artist_name,
            top_tracks=top_tracks,
            genres=genres,
            open_url=open_url,
            followers=followers,
            image_url=image_url
        )

    async def search(self, query: str, type: str = "track", limit: int = 5) -> List[SpotifyTrackMetadata]:
        """Searches Spotify catalog for matching tracks."""
        data = await self._request("search", params={"q": query, "type": type, "limit": limit})
        if not data:
            return []
        items = data.get("tracks", {}).get("items", [])
        return [self._parse_track(item) for item in items if item]

    def _parse_track(self, data: Dict[str, Any], default_artwork: Optional[str] = None) -> SpotifyTrackMetadata:
        """Parses a raw Spotify API track object into SpotifyTrackMetadata."""
        track_id = data.get("id") or ""
        name = data.get("name") or "Unknown Track"
        artists = [a.get("name", "") for a in data.get("artists", []) if a.get("name")]
        
        album_obj = data.get("album", {})
        album_name = album_obj.get("name") or ""
        album_images = album_obj.get("images", [])
        artwork = album_images[0].get("url") if album_images else default_artwork

        duration_ms = int(data.get("duration_ms", 0))
        open_url = data.get("external_urls", {}).get("spotify", f"https://open.spotify.com/track/{track_id}")
        isrc = data.get("external_ids", {}).get("isrc")
        explicit = bool(data.get("explicit", False))
        preview_url = data.get("preview_url")
        release_date = album_obj.get("release_date")
        popularity = data.get("popularity")

        return SpotifyTrackMetadata(
            id=track_id,
            name=name,
            artists=artists,
            album=album_name,
            duration_ms=duration_ms,
            open_url=open_url,
            artwork_url=artwork,
            isrc=isrc,
            explicit=explicit,
            preview_url=preview_url,
            release_date=release_date,
            popularity=popularity
        )
