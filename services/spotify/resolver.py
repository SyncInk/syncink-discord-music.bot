import re
import json
import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple, Any
from utils.logger import log
from services.spotify.client import SpotifyClient
from services.spotify.models import (
    SpotifyTrackMetadata,
    SpotifyAlbumMetadata,
    SpotifyPlaylistMetadata,
    SpotifyArtistMetadata,
    NormalizedTrack,
)

class SpotifyResolver:
    """
    Dedicated Spotify URL and URI parser conforming to Phase 3 & Phase 4 specifications.
    Recognizes tracks, albums, playlists, and artists, retrieving official metadata and
    producing standardized NormalizedTrack objects, with robust zero-key embed fallback.
    """
    # Regex matching open.spotify.com URLs (supporting optional regional prefixes like /intl-de/)
    URL_REGEX = re.compile(
        r'https?://(?:open\.)?spotify\.com/(?:intl-[a-zA-Z]{2}/)?(track|album|playlist|artist)/([a-zA-Z0-9]+)',
        re.IGNORECASE
    )
    # Regex matching Spotify URIs (spotify:track:123456)
    URI_REGEX = re.compile(
        r'spotify:(track|album|playlist|artist):([a-zA-Z0-9]+)',
        re.IGNORECASE
    )

    @classmethod
    def is_spotify_url_or_uri(cls, query: str) -> bool:
        if not query:
            return False
        q = query.strip()
        return bool(cls.URL_REGEX.search(q) or cls.URI_REGEX.search(q))

    @classmethod
    def parse_resource(cls, query: str) -> Optional[Tuple[str, str]]:
        """
        Extracts resource type and ID from a Spotify URL or URI.
        Returns ('track' | 'album' | 'playlist' | 'artist', identifier) or None.
        """
        if not query:
            return None
        q = query.strip()

        match = cls.URL_REGEX.search(q)
        if match:
            return match.group(1).lower(), match.group(2)

        uri_match = cls.URI_REGEX.search(q)
        if uri_match:
            return uri_match.group(1).lower(), uri_match.group(2)

        return None

    @classmethod
    async def extract_embed(
        cls,
        res_type: str,
        res_id: str,
        limit: int = 100
    ) -> Tuple[Optional[str], List[NormalizedTrack], Dict[str, Any]]:
        """
        Zero-API-key scraper extracting rich metadata and full track listings directly
        from Spotify's public embed CDN (open.spotify.com/embed/{type}/{id}).
        """
        embed_url = f"https://open.spotify.com/embed/{res_type}/{res_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        try:
            timeout = aiohttp.ClientTimeout(total=15, connect=5)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(embed_url, headers=headers) as resp:
                    if resp.status != 200:
                        log.debug(f"[Spotify Embed] Embed request failed HTTP {resp.status} for {embed_url}")
                        return res_type, [], {}

                    html = await resp.text()
                    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html)
                    if not m:
                        return res_type, [], {}

                    data = json.loads(m.group(1))
                    entity = data.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
                    if not entity:
                        return res_type, [], {}

                    container_name = entity.get("name") or entity.get("title") or "Spotify Content"
                    raw_authors = entity.get("authors") or []
                    owner_name = ", ".join([a.get("name", "") for a in raw_authors if isinstance(a, dict)]) if raw_authors else (entity.get("subtitle") or "Spotify")
                    description = entity.get("description") or ""

                    # Extract best cover artwork
                    artwork_url = "https://files.catbox.moe/74l9su.png"
                    cover_sources = entity.get("coverArt", {}).get("sources", [])
                    if cover_sources and isinstance(cover_sources, list) and cover_sources[0].get("url"):
                        artwork_url = cover_sources[0]["url"]
                    else:
                        vis_images = entity.get("visualIdentity", {}).get("image", [])
                        if vis_images and isinstance(vis_images, list) and vis_images[-1].get("url"):
                            artwork_url = vis_images[-1]["url"]

                    tracks: List[NormalizedTrack] = []

                    if res_type == "track":
                        t_id = entity.get("id") or res_id
                        t_title = entity.get("name") or entity.get("title") or "Unknown Track"
                        art_list = entity.get("artists") or []
                        if isinstance(art_list, list) and art_list and isinstance(art_list[0], dict):
                            t_artist = ", ".join([a.get("name", "") for a in art_list if a.get("name")])
                        else:
                            t_artist = entity.get("subtitle") or "Unknown Artist"
                        t_dur = int(entity.get("duration", 0))

                        nt = NormalizedTrack(
                            id=t_id,
                            title=t_title,
                            artist=t_artist,
                            album=container_name,
                            duration_ms=t_dur,
                            artwork=artwork_url,
                            source_platform="spotify",
                            original_url=f"https://open.spotify.com/track/{t_id}",
                            isrc=None,
                            explicit=bool(entity.get("isExplicit", False)),
                            playable=False,
                            playback_source=None
                        )
                        return "track", [nt], {
                            "name": t_title,
                            "artist": t_artist,
                            "artwork": artwork_url,
                            "total": 1,
                            "open_url": f"https://open.spotify.com/track/{t_id}"
                        }

                    # Playlist / Album / Artist
                    track_list = entity.get("trackList", [])
                    for t in track_list[:limit]:
                        t_title = t.get("title")
                        if not t_title:
                            continue
                        t_artist = t.get("subtitle") or owner_name
                        t_dur = int(t.get("duration", 0))
                        t_uri = t.get("uri", "")
                        t_id = t_uri.split(":")[-1] if ":" in t_uri else res_id

                        tracks.append(
                            NormalizedTrack(
                                id=t_id,
                                title=t_title,
                                artist=t_artist,
                                album=container_name,
                                duration_ms=t_dur,
                                artwork=artwork_url,
                                source_platform="spotify",
                                original_url=f"https://open.spotify.com/track/{t_id}" if t_id else f"https://open.spotify.com/{res_type}/{res_id}",
                                isrc=None,
                                explicit=bool(t.get("isExplicit", False)),
                                playable=False,
                                playback_source=None
                            )
                        )

                    return res_type, tracks, {
                        "name": container_name,
                        "owner": owner_name,
                        "artist": owner_name,
                        "artwork": artwork_url,
                        "total": len(tracks),
                        "open_url": f"https://open.spotify.com/{res_type}/{res_id}",
                        "description": description
                    }

        except Exception as e:
            log.warning(f"[Spotify Embed Scraper] Error scraping embed for {res_type}/{res_id}: {e}")
            return res_type, [], {}

    @classmethod
    async def resolve(
        cls,
        query: str,
        limit: int = 100,
        user_token: Optional[str] = None
    ) -> Tuple[Optional[str], List[NormalizedTrack], Dict[str, Any]]:
        """
        Resolves a Spotify link into a list of NormalizedTrack objects.
        Automatically uses official Spotify Web API if configured, and seamlessly
        falls back to zero-key embed scraping if unconfigured, rate-limited, or blocked.
        Returns:
            (resource_type, normalized_tracks, container_metadata)
        """
        parsed = cls.parse_resource(query)
        if not parsed:
            return None, [], {}

        res_type, res_id = parsed
        client = SpotifyClient.get_instance()

        if res_type == "track":
            meta = None
            if client.is_configured:
                try:
                    meta = await client.get_track(res_id, user_token=user_token)
                except Exception as e:
                    log.debug(f"[Spotify Resolver] get_track official API failed: {e}")
            if meta:
                normalized = cls.normalize_track(meta)
                return "track", [normalized], {
                    "name": meta.name,
                    "artist": meta.artist_name,
                    "artwork": meta.artwork_url,
                    "total": 1,
                    "open_url": meta.open_url,
                }
            # Fallback to embed
            return await cls.extract_embed("track", res_id, limit=1)

        elif res_type == "album":
            album = None
            if client.is_configured:
                try:
                    album = await client.get_album(res_id, limit=limit, user_token=user_token)
                except Exception as e:
                    log.debug(f"[Spotify Resolver] get_album official API failed: {e}")
            if album:
                tracks = [cls.normalize_track(t) for t in album.tracks]
                return "album", tracks, {
                    "name": album.name,
                    "artist": album.artist_name,
                    "artwork": album.artwork_url,
                    "total": album.total_tracks,
                    "open_url": album.open_url,
                }
            # Fallback to embed
            return await cls.extract_embed("album", res_id, limit=limit)

        elif res_type == "playlist":
            playlist = None
            if client.is_configured:
                try:
                    playlist = await client.get_playlist(res_id, limit=limit, user_token=user_token)
                except Exception as e:
                    log.debug(f"[Spotify Resolver] get_playlist official API failed: {e}")
            if playlist:
                tracks = [cls.normalize_track(t) for t in playlist.tracks]
                return "playlist", tracks, {
                    "name": playlist.name,
                    "owner": playlist.owner_name,
                    "artwork": playlist.artwork_url,
                    "total": playlist.total_tracks,
                    "open_url": playlist.open_url,
                    "description": playlist.description,
                }
            # Fallback to embed
            return await cls.extract_embed("playlist", res_id, limit=limit)

        elif res_type == "artist":
            artist = None
            if client.is_configured:
                try:
                    artist = await client.get_artist_top_tracks(res_id, user_token=user_token)
                except Exception as e:
                    log.debug(f"[Spotify Resolver] get_artist_top_tracks official API failed: {e}")
            if artist:
                tracks = [cls.normalize_track(t) for t in artist.top_tracks]
                return "artist", tracks, {
                    "name": artist.name,
                    "artwork": artist.image_url,
                    "genres": artist.genres,
                    "total": len(tracks),
                    "open_url": artist.open_url,
                }
            # Fallback to embed
            return await cls.extract_embed("artist", res_id, limit=limit)

        return None, [], {}

    @classmethod
    def normalize_track(cls, track: SpotifyTrackMetadata) -> NormalizedTrack:
        """Converts SpotifyTrackMetadata into a standardized NormalizedTrack."""
        return NormalizedTrack(
            id=track.id,
            title=track.name,
            artist=track.artist_name,
            album=track.album,
            duration_ms=track.duration_ms,
            artwork=track.artwork_url,
            source_platform="spotify",
            original_url=track.open_url,
            isrc=track.isrc,
            explicit=track.explicit,
            playable=False,
            playback_source=None,
        )
