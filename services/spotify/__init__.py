"""
services/spotify
Production-quality Spotify integration for SyncInk Radio.
Provides Client Credentials API, User OAuth with PKCE, URL/URI resolution,
and normalized metadata conforming to Unified Music Resolver architecture.
"""

from services.spotify.models import (
    SpotifyTrackMetadata,
    SpotifyAlbumMetadata,
    SpotifyPlaylistMetadata,
    SpotifyArtistMetadata,
    NormalizedTrack,
    SpotifyUserAuth,
)
from services.spotify.client import SpotifyClient, SpotifyAPIError
from services.spotify.resolver import SpotifyResolver
from services.spotify.auth import SpotifyUserAuthManager
from services.spotify.web_server import start_spotify_web_server, stop_spotify_web_server

__all__ = [
    "SpotifyTrackMetadata",
    "SpotifyAlbumMetadata",
    "SpotifyPlaylistMetadata",
    "SpotifyArtistMetadata",
    "NormalizedTrack",
    "SpotifyUserAuth",
    "SpotifyClient",
    "SpotifyAPIError",
    "SpotifyResolver",
    "SpotifyUserAuthManager",
    "start_spotify_web_server",
    "stop_spotify_web_server",
]
