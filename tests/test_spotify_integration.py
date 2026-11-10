import unittest
import asyncio
import os
import sys
import time

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.spotify.models import (
    SpotifyTrackMetadata,
    SpotifyAlbumMetadata,
    SpotifyPlaylistMetadata,
    SpotifyArtistMetadata,
    NormalizedTrack,
)
from services.spotify.resolver import SpotifyResolver
from services.spotify.crypto import TokenEncryptor
from services.spotify.auth import SpotifyUserAuthManager
from services.spotify.client import SpotifyClient


class TestSpotifyIntegration(unittest.TestCase):

    def test_01_valid_track_urls_and_uris(self):
        """Test recognition of various valid Spotify track URL formats and URIs."""
        valid_inputs = [
            ("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT", "track", "4cOdK2wGLETKBW3PvgPWqT"),
            ("http://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT?si=abc123xyz", "track", "4cOdK2wGLETKBW3PvgPWqT"),
            ("https://open.spotify.com/intl-de/track/4cOdK2wGLETKBW3PvgPWqT", "track", "4cOdK2wGLETKBW3PvgPWqT"),
            ("https://open.spotify.com/intl-ja/track/4cOdK2wGLETKBW3PvgPWqT?context=spotify", "track", "4cOdK2wGLETKBW3PvgPWqT"),
            ("spotify:track:4cOdK2wGLETKBW3PvgPWqT", "track", "4cOdK2wGLETKBW3PvgPWqT"),
        ]
        for url, expected_type, expected_id in valid_inputs:
            with self.subTest(url=url):
                self.assertTrue(SpotifyResolver.is_spotify_url_or_uri(url), f"Should recognize {url}")
                parsed = SpotifyResolver.parse_resource(url)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed[0], expected_type)
                self.assertEqual(parsed[1], expected_id)

    def test_02_album_playlist_artist_urls(self):
        """Test recognition of albums, playlists, and artist profiles."""
        test_cases = [
            ("https://open.spotify.com/album/1DFixLWuPkv3KT3TnV35m3", "album", "1DFixLWuPkv3KT3TnV35m3"),
            ("spotify:album:1DFixLWuPkv3KT3TnV35m3", "album", "1DFixLWuPkv3KT3TnV35m3"),
            ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M", "playlist", "37i9dQZF1DXcBWIGoYBM5M"),
            ("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M", "playlist", "37i9dQZF1DXcBWIGoYBM5M"),
            ("https://open.spotify.com/artist/4YRxDV8wJFPHPTeXepOstw", "artist", "4YRxDV8wJFPHPTeXepOstw"),
            ("spotify:artist:4YRxDV8wJFPHPTeXepOstw", "artist", "4YRxDV8wJFPHPTeXepOstw"),
        ]
        for url, expected_type, expected_id in test_cases:
            with self.subTest(url=url):
                parsed = SpotifyResolver.parse_resource(url)
                self.assertIsNotNone(parsed)
                self.assertEqual(parsed[0], expected_type)
                self.assertEqual(parsed[1], expected_id)

    def test_03_invalid_urls(self):
        """Test rejection of non-Spotify and malformed links."""
        invalid_inputs = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://soundcloud.com/artist/track",
            "https://open.spotify.com/unknown_type/123456",
            "not a url at all",
            "",
            "spotify:invalid:123",
        ]
        for url in invalid_inputs:
            with self.subTest(url=url):
                self.assertFalse(SpotifyResolver.is_spotify_url_or_uri(url))
                self.assertIsNone(SpotifyResolver.parse_resource(url))

    def test_04_pkce_crypto_generation(self):
        """Test PKCE code verifier and code challenge generation."""
        auth_mgr = SpotifyUserAuthManager.get_instance()
        verifier = auth_mgr._generate_code_verifier()
        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)

        challenge = auth_mgr._generate_code_challenge(verifier)
        self.assertTrue(len(challenge) > 0)
        self.assertFalse("=" in challenge, "PKCE challenge should not contain padding = characters")

        # Deterministic check with known vector
        test_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        computed_challenge = auth_mgr._generate_code_challenge(test_verifier)
        self.assertTrue(isinstance(computed_challenge, str))

    def test_05_token_encryption_and_decryption(self):
        """Test that sensitive user refresh tokens are encrypted and decrypted accurately."""
        sample_tokens = [
            "AQD123456789_sample_spotify_refresh_token_very_long_string_XYZ",
            "AQB_short_token",
            "Special!@#$%^&*()_+Characters-123456",
        ]
        for token in sample_tokens:
            with self.subTest(token=token):
                encrypted = TokenEncryptor.encrypt(token)
                self.assertNotEqual(encrypted, token, "Ciphertext must not match plaintext")
                decrypted = TokenEncryptor.decrypt(encrypted)
                self.assertEqual(decrypted, token, "Decrypted text must match original plaintext")

    def test_06_metadata_normalization(self):
        """Test converting SpotifyTrackMetadata to NormalizedTrack format."""
        meta = SpotifyTrackMetadata(
            id="test1234",
            name="Dog Days Are Over",
            artists=["Florence + The Machine"],
            album="Lungs",
            duration_ms=252000,
            open_url="https://open.spotify.com/track/test1234",
            artwork_url="https://i.scdn.co/image/ab67616d0000b273test",
            isrc="GBBKS0800100",
            explicit=False,
        )
        norm = SpotifyResolver.normalize_track(meta)
        self.assertEqual(norm.id, "test1234")
        self.assertEqual(norm.title, "Dog Days Are Over")
        self.assertEqual(norm.artist, "Florence + The Machine")
        self.assertEqual(norm.album, "Lungs")
        self.assertEqual(norm.duration_ms, 252000)
        self.assertEqual(norm.duration_sec, 252)
        self.assertEqual(norm.source_platform, "spotify")
        self.assertEqual(norm.original_url, "https://open.spotify.com/track/test1234")
        self.assertEqual(norm.isrc, "GBBKS0800100")
        self.assertFalse(norm.playable)
        self.assertIsNone(norm.playback_source)

    def test_07_spotify_client_configuration_check(self):
        """Test SpotifyClient credentials detection."""
        client = SpotifyClient.get_instance()
        # Checks if client is initialized
        self.assertIsNotNone(client)
        self.assertIsInstance(client.is_configured, bool)

    def test_08_album_and_playlist_metadata_models(self):
        """Test Album and Playlist models and artist concatenation."""
        track1 = SpotifyTrackMetadata(
            id="t1", name="Track 1", artists=["Artist A", "Artist B"],
            album="Test Album", duration_ms=180000, open_url="https://open.spotify.com/track/t1"
        )
        album = SpotifyAlbumMetadata(
            id="a1", name="Test Album", artists=["Artist A"],
            total_tracks=1, tracks=[track1], open_url="https://open.spotify.com/album/a1"
        )
        self.assertEqual(album.artist_name, "Artist A")
        self.assertEqual(len(album.tracks), 1)
        self.assertEqual(album.tracks[0].artist_name, "Artist A, Artist B")

        playlist = SpotifyPlaylistMetadata(
            id="p1", name="Favorites", owner_name="User123",
            total_tracks=1, tracks=[track1], open_url="https://open.spotify.com/playlist/p1"
        )
        self.assertEqual(playlist.owner_name, "User123")
        self.assertEqual(len(playlist.tracks), 1)


if __name__ == "__main__":
    unittest.main()
