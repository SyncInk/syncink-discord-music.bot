import re
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
    producing standardized NormalizedTrack objects.
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
    async def resolve(
        cls,
        query: str,
        limit: int = 100,
        user_token: Optional[str] = None
    ) -> Tuple[Optional[str], List[NormalizedTrack], Dict[str, Any]]:
        """
        Resolves a Spotify link into a list of NormalizedTrack objects.
        Returns:
            (resource_type, normalized_tracks, container_metadata)
        """
        parsed = cls.parse_resource(query)
        if not parsed:
            return None, [], {}

        res_type, res_id = parsed
        client = SpotifyClient.get_instance()

        if res_type == "track":
            meta = await client.get_track(res_id, user_token=user_token)
            if not meta:
                return "track", [], {}
            normalized = cls.normalize_track(meta)
            return "track", [normalized], {
                "name": meta.name,
                "artist": meta.artist_name,
                "artwork": meta.artwork_url,
                "total": 1,
            }

        elif res_type == "album":
            album = await client.get_album(res_id, limit=limit, user_token=user_token)
            if not album:
                return "album", [], {}
            tracks = [cls.normalize_track(t) for t in album.tracks]
            return "album", tracks, {
                "name": album.name,
                "artist": album.artist_name,
                "artwork": album.artwork_url,
                "total": album.total_tracks,
                "open_url": album.open_url,
            }

        elif res_type == "playlist":
            playlist = await client.get_playlist(res_id, limit=limit, user_token=user_token)
            if not playlist:
                return "playlist", [], {}
            tracks = [cls.normalize_track(t) for t in playlist.tracks]
            return "playlist", tracks, {
                "name": playlist.name,
                "owner": playlist.owner_name,
                "artwork": playlist.artwork_url,
                "total": playlist.total_tracks,
                "open_url": playlist.open_url,
                "description": playlist.description,
            }

        elif res_type == "artist":
            artist = await client.get_artist_top_tracks(res_id, user_token=user_token)
            if not artist:
                return "artist", [], {}
            tracks = [cls.normalize_track(t) for t in artist.top_tracks]
            return "artist", tracks, {
                "name": artist.name,
                "artwork": artist.image_url,
                "genres": artist.genres,
                "total": len(tracks),
                "open_url": artist.open_url,
            }

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
