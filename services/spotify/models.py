from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

@dataclass
class SpotifyTrackMetadata:
    id: str
    name: str
    artists: List[str]
    album: str
    duration_ms: int
    open_url: str
    artwork_url: Optional[str] = None
    isrc: Optional[str] = None
    explicit: bool = False
    preview_url: Optional[str] = None
    release_date: Optional[str] = None
    popularity: Optional[int] = None

    @property
    def artist_name(self) -> str:
        return ", ".join(self.artists) if self.artists else "Unknown Artist"

    @property
    def duration_sec(self) -> int:
        return max(1, self.duration_ms // 1000)

@dataclass
class SpotifyAlbumMetadata:
    id: str
    name: str
    artists: List[str]
    total_tracks: int
    tracks: List[SpotifyTrackMetadata]
    open_url: str
    artwork_url: Optional[str] = None
    release_date: Optional[str] = None

    @property
    def artist_name(self) -> str:
        return ", ".join(self.artists) if self.artists else "Unknown Artist"

@dataclass
class SpotifyPlaylistMetadata:
    id: str
    name: str
    owner_name: str
    total_tracks: int
    tracks: List[SpotifyTrackMetadata]
    open_url: str
    artwork_url: Optional[str] = None
    description: Optional[str] = None

@dataclass
class SpotifyArtistMetadata:
    id: str
    name: str
    top_tracks: List[SpotifyTrackMetadata]
    genres: List[str]
    open_url: str
    followers: Optional[int] = None
    image_url: Optional[str] = None

@dataclass
class NormalizedTrack:
    """
    Standardized, cross-platform track representation conforming to
    SyncInk Radio Unified Music Resolver architecture (Phase 4).
    """
    id: str
    title: str
    artist: str
    album: str
    duration_ms: int
    artwork: Optional[str]
    source_platform: str  # "spotify"
    original_url: str
    playable: bool = False
    playback_source: Optional[str] = None
    isrc: Optional[str] = None
    explicit: bool = False

    @property
    def duration_sec(self) -> int:
        return max(1, self.duration_ms // 1000)

@dataclass
class SpotifyUserAuth:
    discord_user_id: int
    spotify_user_id: str
    display_name: Optional[str]
    email: Optional[str]
    access_token: Optional[str]
    encrypted_refresh_token: Optional[str]
    expires_at: float = 0.0
    scope: Optional[str] = None
