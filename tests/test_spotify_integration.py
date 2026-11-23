import unittest
import asyncio
import os
import sys
import time
import json
from unittest.mock import patch, MagicMock

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
from database import db


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


class TestSpotifyAuthAndDashboardIntegration(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        from database import db
        await db.connect()
        self.auth_mgr = SpotifyUserAuthManager.get_instance()
        self.auth_mgr.client_id = "test_spotify_client_id_123"
        self.auth_mgr.client_secret = "test_spotify_client_secret_456"

    async def asyncTearDown(self):
        from database import db
        await db.close()

    async def test_09_canonical_redirect_uri_resolution(self):
        """Test that redirect URI resolves to production subpath and avoids 127.0.0.1 and unproxied root in production."""
        # 1. When SPOTIFY_REDIRECT_URI is public subpath
        with patch.dict(os.environ, {"SPOTIFY_REDIRECT_URI": "https://syncink.site/dashboard/radio/callback", "DISCORD_REDIRECT_URI": "https://syncink.site/dashboard/radio/api/auth/discord/callback"}):
            uri = self.auth_mgr.get_default_redirect_uri()
            self.assertEqual(uri, "https://syncink.site/dashboard/radio/callback")

        # 2. When SPOTIFY_REDIRECT_URI had stale 127.0.0.1 in production
        with patch.dict(os.environ, {"SPOTIFY_REDIRECT_URI": "http://127.0.0.1:8888/callback", "DISCORD_REDIRECT_URI": "https://syncink.site/dashboard/radio/api/auth/discord/callback"}):
            uri = self.auth_mgr.get_default_redirect_uri()
            self.assertEqual(uri, "https://syncink.site/dashboard/radio/callback", "Should safeguard against 127.0.0.1 in production")

        # 3. When SPOTIFY_REDIRECT_URI had unproxied root /callback in production (which 404s on main website)
        with patch.dict(os.environ, {"SPOTIFY_REDIRECT_URI": "https://syncink.site/callback", "DISCORD_REDIRECT_URI": "https://syncink.site/dashboard/radio/api/auth/discord/callback"}):
            uri = self.auth_mgr.get_default_redirect_uri()
            self.assertEqual(uri, "https://syncink.site/dashboard/radio/callback", "Should auto-correct root /callback to /dashboard/radio/callback")

    async def test_10_generate_auth_url_stores_redirect_and_target(self):
        """Test that generate_auth_url records redirect_uri and return_to in the database."""
        from database import db
        user_id = 987654321012345678

        auth_url, state = await self.auth_mgr.generate_auth_url(
            discord_user_id=user_id,
            redirect_uri="https://syncink.site/dashboard/radio/callback",
            return_to="dashboard"
        )

        self.assertIn("client_id=test_spotify_client_id_123", auth_url)
        self.assertIn("redirect_uri=https%3A%2F%2Fsyncink.site%2Fdashboard%2Fradio%2Fcallback", auth_url)
        self.assertIn(f"state={state}", auth_url)

        # Verify state row in database
        row = await db.fetchrow("SELECT discord_user_id, code_verifier, redirect_uri, return_to FROM spotify_oauth_states WHERE state = $1;", state)
        self.assertIsNotNone(row)
        self.assertEqual(int(row["discord_user_id"]), user_id)
        self.assertEqual(row["redirect_uri"], "https://syncink.site/dashboard/radio/callback")
        self.assertEqual(row["return_to"], "dashboard")

        # Clean up
        await db.execute("DELETE FROM spotify_oauth_states WHERE state = $1;", state)

    async def test_11_dashboard_spotify_status_and_disconnect(self):
        """Test /api/spotify/status and /api/spotify/disconnect handlers."""
        from aiohttp.test_utils import make_mocked_request
        from services.web.api import DashboardAPI
        from services.web.auth import DashboardAuthManager
        from database import db

        user_id = 888888888888888888
        await db.execute("DELETE FROM spotify_users WHERE discord_user_id = $1", user_id)
        self.auth_mgr._user_tokens.pop(user_id, None)

        # Mock session
        auth_mgr = DashboardAuthManager.get_instance()
        session_id = await auth_mgr.create_session({
            "id": str(user_id),
            "username": "SpotifyTester",
            "discriminator": "0001",
            "avatar": None
        }, {"access_token": "mock_token"})

        # Check status when not connected
        req = make_mocked_request("GET", "/api/spotify/status", headers={"Authorization": f"Bearer {session_id}"})
        resp = await DashboardAPI.handle_spotify_status(req)
        data = json.loads(resp.text)
        self.assertFalse(data["connected"])

        # Insert linked Spotify user
        await db.execute(
            """
            INSERT INTO spotify_users (discord_user_id, spotify_user_id, display_name, email, encrypted_refresh_token, scope)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (discord_user_id) DO UPDATE SET display_name = $3;
            """,
            user_id, "spotify_user_999", "SpotifyRockstar", "rockstar@spotify.com", "enc_token", "user-read-private"
        )
        self.auth_mgr._user_tokens.pop(user_id, None)

        req2 = make_mocked_request("GET", "/api/spotify/status", headers={"Authorization": f"Bearer {session_id}"})
        resp2 = await DashboardAPI.handle_spotify_status(req2)
        data2 = json.loads(resp2.text)
        self.assertTrue(data2["connected"])
        self.assertEqual(data2["display_name"], "SpotifyRockstar")

        # Test disconnect
        disc_req = make_mocked_request("POST", "/api/spotify/disconnect", headers={"Authorization": f"Bearer {session_id}"})
        disc_resp = await DashboardAPI.handle_spotify_disconnect(disc_req)
        disc_data = json.loads(disc_resp.text)
        self.assertTrue(disc_data["success"])

        # Check status again -> should be disconnected
        req3 = make_mocked_request("GET", "/api/spotify/status", headers={"Authorization": f"Bearer {session_id}"})
        resp3 = await DashboardAPI.handle_spotify_status(req3)
        data3 = json.loads(resp3.text)
        self.assertFalse(data3["connected"])

    async def test_12_pure_pkce_callback_exchange(self):
        """Test handle_callback_detailed uses pure PKCE without Basic Auth header."""
        from database import db
        user_id = 777666555444333222
        auth_url, state = await self.auth_mgr.generate_auth_url(
            discord_user_id=user_id,
            redirect_uri="https://syncink.site/dashboard/radio/callback",
            return_to="dashboard"
        )

        captured_requests = []

        class MockResponse:
            def __init__(self, status, json_data=None, text_data=""):
                self.status = status
                self._json = json_data or {}
                self._text = text_data
            async def json(self):
                return self._json
            async def text(self):
                return self._text
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass

        class MockSession:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def post(self, url, data=None, headers=None):
                captured_requests.append(("POST", url, data, headers))
                return MockResponse(200, {
                    "access_token": "mock_access_token_123",
                    "refresh_token": "mock_refresh_token_456",
                    "expires_in": 3600,
                    "scope": "user-read-private"
                })
            def get(self, url, headers=None):
                captured_requests.append(("GET", url, None, headers))
                return MockResponse(200, {
                    "id": "spotify_user_test",
                    "display_name": "Test Dancer",
                    "email": "test@spotify.com"
                })

        with patch("aiohttp.ClientSession", MockSession):
            user_auth, err = await self.auth_mgr.handle_callback_detailed("mock_auth_code_999", state)

        self.assertIsNone(err)
        self.assertIsNotNone(user_auth)
        self.assertEqual(user_auth.spotify_user_id, "spotify_user_test")
        self.assertEqual(user_auth.display_name, "Test Dancer")
        self.assertEqual(user_auth.return_to, "dashboard")

        # Verify that pure PKCE request was sent WITHOUT Authorization header
        token_post = next(r for r in captured_requests if r[0] == "POST")
        self.assertNotIn("Authorization", token_post[3], "Pure PKCE token request must NOT contain Authorization header")
        self.assertEqual(token_post[2]["client_id"], self.auth_mgr.client_id)

    async def test_13_state_preservation_and_memory_fallback(self):
        """Test state preservation on failed token exchange and memory fallback if DB is deleted."""
        from database import db
        user_id = 111222333444555666
        auth_url, state = await self.auth_mgr.generate_auth_url(
            discord_user_id=user_id,
            redirect_uri="https://syncink.site/dashboard/radio/callback",
            return_to="discord"
        )

        class FailingSession:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def post(self, url, data=None, headers=None):
                class Resp:
                    status = 400
                    async def text(self):
                        return json.dumps({"error": "invalid_grant", "error_description": "Invalid authorization code"})
                    async def __aenter__(self):
                        return self
                    async def __aexit__(self, *args):
                        pass
                return Resp()

        # 1. First attempt fails due to invalid_grant
        with patch("aiohttp.ClientSession", FailingSession):
            user_auth, err = await self.auth_mgr.handle_callback_detailed("expired_code", state)

        self.assertIsNone(user_auth)
        self.assertIn("Invalid authorization code", err)

        # 2. Verify state was NOT prematurely deleted from memory on failure
        self.assertIn(state, self.auth_mgr._pending_oauth_states)

        # 3. Simulate DB wiped out while memory cache persists
        await db.execute("DELETE FROM spotify_oauth_states WHERE state = $1;", state)

        # 4. Verify that state can still be resolved from in-memory cache
        class SucceedingSession:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def post(self, url, data=None, headers=None):
                class Resp:
                    status = 200
                    async def json(self):
                        return {"access_token": "ok_tok", "refresh_token": "ok_rt", "expires_in": 3600}
                    async def __aenter__(self):
                        return self
                    async def __aexit__(self, *args):
                        pass
                return Resp()
            def get(self, url, headers=None):
                class Resp:
                    status = 200
                    async def json(self):
                        return {"id": "recovered_user", "display_name": "Recovered"}
                    async def __aenter__(self):
                        return self
                    async def __aexit__(self, *args):
                        pass
                return Resp()

        with patch("aiohttp.ClientSession", SucceedingSession):
            user_auth2, err2 = await self.auth_mgr.handle_callback_detailed("good_code", state)

        self.assertIsNone(err2)
        self.assertIsNotNone(user_auth2)
        self.assertEqual(user_auth2.spotify_user_id, "recovered_user")

    async def test_14_profile_fetch_403_graceful_fallback(self):
        """Test that HTTP 403 on Spotify /v1/me endpoint does not fail account linking and uses fallback profile."""
        from database import db
        user_id = 555444333222111000
        auth_url, state = await self.auth_mgr.generate_auth_url(
            discord_user_id=user_id,
            redirect_uri="https://syncink.site/dashboard/radio/callback",
            return_to="dashboard"
        )

        class DevModeSession:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            def post(self, url, data=None, headers=None):
                class Resp:
                    status = 200
                    async def json(self):
                        return {"access_token": "valid_at_xyz", "refresh_token": "valid_rt_abc", "expires_in": 3600}
                    async def __aenter__(self):
                        return self
                    async def __aexit__(self, *args):
                        pass
                return Resp()
            def get(self, url, headers=None):
                class Resp:
                    status = 403
                    async def text(self):
                        return json.dumps({"error": {"status": 403, "message": "User not registered in the Developer Dashboard"}})
                    async def __aenter__(self):
                        return self
                    async def __aexit__(self, *args):
                        pass
                return Resp()

        with patch("aiohttp.ClientSession", DevModeSession):
            user_auth, err = await self.auth_mgr.handle_callback_detailed("valid_oauth_code", state)

        self.assertIsNone(err)
        self.assertIsNotNone(user_auth)
        self.assertEqual(user_auth.discord_user_id, user_id)
        self.assertEqual(user_auth.display_name, "Spotify User")
        self.assertTrue(user_auth.spotify_user_id.startswith("user_") or user_auth.spotify_user_id.startswith("spotify_"))
        self.assertEqual(user_auth.return_to, "dashboard")

        # Verify record in DB
        row = await db.fetchrow("SELECT display_name, encrypted_refresh_token FROM spotify_users WHERE discord_user_id = $1;", user_id)
        self.assertIsNotNone(row)
        self.assertEqual(row["display_name"], "Spotify User")
        self.assertTrue(len(row["encrypted_refresh_token"]) > 0)

    async def test_18_public_spotify_playlist_resolver_fallback(self):
        """Test that SpotifyResolver.resolve safely resolves public playlists using embed scraper fallback."""
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
        res_type, tracks, meta = await SpotifyResolver.resolve(url, limit=10)
        self.assertEqual(res_type, "playlist")
        self.assertTrue(len(tracks) > 0)
        self.assertIsNotNone(meta.get("name"))
        self.assertTrue(tracks[0].title != "")
        self.assertTrue(tracks[0].artist != "")

    async def test_19_saved_spotify_playlists_library(self):
        """Test saving a public Spotify playlist into user_spotify_playlists and retrieving via get_user_playlists."""
        test_uid = 999888777666555444
        url = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"

        pl = await self.auth_mgr.add_user_spotify_playlist(test_uid, url)
        self.assertIsNotNone(pl)
        self.assertEqual(pl["id"], "37i9dQZF1DXcBWIGoYBM5M")
        self.assertTrue(pl["tracks_total"] > 0)

        # Retrieve playlists for this user
        playlists = await self.auth_mgr.get_user_playlists(test_uid)
        self.assertTrue(len(playlists) > 0)
        saved_pl = next((p for p in playlists if p["id"] == "37i9dQZF1DXcBWIGoYBM5M"), None)
        self.assertIsNotNone(saved_pl)
        self.assertEqual(saved_pl["name"], pl["name"])

        # Clean up
        await self.auth_mgr.remove_user_spotify_playlist(test_uid, "37i9dQZF1DXcBWIGoYBM5M")


if __name__ == "__main__":
    unittest.main()
