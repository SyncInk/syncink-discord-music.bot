import asyncio
import os
import sys
import unittest
import json
from unittest.mock import MagicMock, AsyncMock, patch

# Ensure root dir in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import db
from services.web.auth import DashboardAuthManager
from services.web.websocket import DashboardWebSocketManager, notify_guild_playback_changed
from services.web.server import UnifiedWebServer
from services.music_service import MusicService, Track
from services.autoplay_service import AutoPlayService
from services.radio_service import RadioService

class TestDashboardCompleteIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Connect to local SQLite DB for test isolation
        await db.connect()
        self.auth_mgr = DashboardAuthManager.get_instance()
        self.ws_mgr = DashboardWebSocketManager.get_instance()
        self.music_service = MusicService.get_instance()
        self.autoplay_service = AutoPlayService.get_instance()
        self.radio_service = RadioService.get_instance()

        # Mock Bot instance
        self.mock_bot = MagicMock()
        self.mock_bot.user = MagicMock()
        self.mock_bot.user.id = 1500567606648897819
        self.mock_bot.user.__str__ = lambda x: "SyncInk Radio#0001"
        self.mock_bot.latency = 0.015

        # Create mock guild 1 and guild 2 for multi-server isolation
        self.mock_guild1 = MagicMock()
        self.mock_guild1.id = 111111111111111111
        self.mock_guild1.name = "SyncInk Testing Guild"
        self.mock_guild1.icon = None
        self.mock_guild1.owner_id = 999999999999999999  # Test Owner
        self.mock_guild1.member_count = 42

        # Mock text channel
        mock_channel = MagicMock()
        mock_channel.id = 222222222222222222
        mock_channel.name = "music-commands"
        self.mock_guild1.text_channels = [mock_channel]

        # Mock voice channel
        mock_vc = MagicMock()
        mock_vc.id = 333333333333333333
        mock_vc.name = "Music Lounge"
        mock_vc.members = []
        self.mock_guild1.voice_channels = [mock_vc]

        # Mock role
        mock_role = MagicMock()
        mock_role.id = 444444444444444444
        mock_role.name = "DJ"
        mock_role.color.value = 0x8055D9
        mock_role.is_default = lambda: False
        self.mock_guild1.roles = [mock_role]

        # Guild 2 (isolated)
        self.mock_guild2 = MagicMock()
        self.mock_guild2.id = 555555555555555555
        self.mock_guild2.name = "Second Guild"
        self.mock_guild2.icon = None
        self.mock_guild2.owner_id = 888888888888888888
        self.mock_guild2.text_channels = []
        self.mock_guild2.voice_channels = []
        self.mock_guild2.roles = []

        self.mock_bot.guilds = [self.mock_guild1, self.mock_guild2]
        self.mock_bot.get_guild = lambda gid: self.mock_guild1 if gid == self.mock_guild1.id else (self.mock_guild2 if gid == self.mock_guild2.id else None)

        # Setup test web server
        self.web_server = UnifiedWebServer(port=8899, bot=self.mock_bot)

    async def asyncTearDown(self):
        await db.close()

    # ---------------- 1. Database & Migrations Test ----------------
    async def test_01_database_tables_exist(self):
        """Verifies all required tables and indexes exist in the database."""
        row_sessions = await db.fetch("SELECT * FROM user_sessions LIMIT 1")
        self.assertIsInstance(row_sessions, list)

        row_favs = await db.fetch("SELECT * FROM user_favorites LIMIT 1")
        self.assertIsInstance(row_favs, list)

        row_hist = await db.fetch("SELECT * FROM listening_history LIMIT 1")
        self.assertIsInstance(row_hist, list)

        row_prefs = await db.fetch("SELECT * FROM user_preferences LIMIT 1")
        self.assertIsInstance(row_prefs, list)

        row_playlists = await db.fetch("SELECT * FROM user_playlists LIMIT 1")
        self.assertIsInstance(row_playlists, list)

    # ---------------- 2. OAuth2 & Session Lifecycle Test ----------------
    async def test_02_auth_and_session_lifecycle(self):
        """Verifies session creation, retrieval, and destruction."""
        user_data = {
            "id": "999999999999999999",
            "username": "SyncInkDev",
            "discriminator": "0",
            "avatar": "abcdef123456"
        }
        token_data = {
            "access_token": "test_access_token_xyz",
            "refresh_token": "test_refresh_token_xyz",
            "expires_in": 3600
        }
        session_id = await self.auth_mgr.create_session(user_data, token_data)
        self.assertIsInstance(session_id, str)
        self.assertEqual(len(session_id), 64)

        # Retrieve session
        session = await self.auth_mgr.get_session(session_id)
        self.assertIsNotNone(session)
        self.assertEqual(session["discord_user_id"], 999999999999999999)
        self.assertEqual(session["username"], "SyncInkDev")

        # Destroy session
        await self.auth_mgr.destroy_session(session_id)
        destroyed = await self.auth_mgr.get_session(session_id)
        self.assertIsNone(destroyed)

    # ---------------- 3. Permission Checks & RBAC ----------------
    async def test_03_server_side_permission_verification(self):
        """Verifies server-side permission checks for administrators vs regular listeners."""
        owner_id = 999999999999999999
        regular_id = 123456789012345678

        # Owner has manage permissions
        self.assertTrue(self.auth_mgr.can_manage_guild(owner_id, self.mock_guild1))

        # Regular user without roles has no manage permissions
        self.mock_guild1.get_member = lambda uid: None
        self.assertFalse(self.auth_mgr.can_manage_guild(regular_id, self.mock_guild1))

        # Member with administrator permissions has manage permissions
        mock_admin_member = MagicMock()
        mock_admin_member.guild_permissions.administrator = True
        self.mock_guild1.get_member = lambda uid: mock_admin_member if uid == 777777777777777777 else None
        self.assertTrue(self.auth_mgr.can_manage_guild(777777777777777777, self.mock_guild1))

        # System Admin check
        with patch.dict(os.environ, {"BOT_OWNER_ID": "999999999999999999"}):
            self.assertTrue(self.auth_mgr.is_system_admin(owner_id, self.mock_bot))
            self.assertFalse(self.auth_mgr.is_system_admin(regular_id, self.mock_bot))

    # ---------------- 4. Real-time WebSocket Serialization & Isolation ----------------
    async def test_04_websocket_playback_serialization(self):
        """Verifies playback snapshot serialization matches 1-second sync specifications."""
        g1_id = self.mock_guild1.id
        queue = self.music_service.get_queue(g1_id)
        queue.volume = 85
        queue.repeat_mode = "track"
        queue.autoplay = True
        queue.last_autoplay_meta = {
            "reason": "Seamless harmonic match with previous Indie Pop song.",
            "genre": "Indie Pop",
            "confidence": 0.95
        }

        # Create a mock track
        test_track = Track(
            title="Golden Hour",
            clean_title="Golden Hour",
            author="JVKE",
            duration=209,
            url="https://www.youtube.com/watch?v=PEM0Vs8jf1w",
            stream_url="https://audio.stream/golden_hour.opus",
            thumbnail="https://i.ytimg.com/vi/PEM0Vs8jf1w/hqdefault.jpg",
            platform="youtube",
            requested_by=None
        )
        queue.current_track = test_track

        # Serialize playback
        snapshot = self.ws_mgr.serialize_guild_playback(g1_id, self.mock_bot)
        self.assertEqual(snapshot["guild_id"], str(g1_id))
        self.assertEqual(snapshot["server_name"], "SyncInk Testing Guild")
        self.assertEqual(snapshot["volume"], 85)
        self.assertEqual(snapshot["repeat_mode"], "track")
        self.assertTrue(snapshot["autoplay"])
        self.assertIsNotNone(snapshot["current_track"])
        self.assertEqual(snapshot["current_track"]["clean_title"] if "clean_title" in snapshot["current_track"] else snapshot["current_track"]["title"], "Golden Hour")
        self.assertIsNotNone(snapshot["autoplay_meta"])
        self.assertIn("Seamless harmonic match", snapshot["autoplay_meta"]["reason"])
        self.assertIn("server_time", snapshot)

    async def test_05_multi_server_state_isolation(self):
        """Verifies Server A playback does not leak into Server B."""
        g1_id = self.mock_guild1.id
        g2_id = self.mock_guild2.id

        q1 = self.music_service.get_queue(g1_id)
        q2 = self.music_service.get_queue(g2_id)

        q1.volume = 120
        q1.active_radio_station = "Lofi Beats Radio"

        q2.volume = 60
        q2.active_radio_station = None

        snap1 = self.ws_mgr.serialize_guild_playback(g1_id, self.mock_bot)
        snap2 = self.ws_mgr.serialize_guild_playback(g2_id, self.mock_bot)

        self.assertEqual(snap1["volume"], 120)
        self.assertEqual(snap1["radio_station"], "Lofi Beats Radio")

        self.assertEqual(snap2["volume"], 60)
        self.assertIsNone(snap2["radio_station"])

    # ---------------- 5. Audia AI Recommendation Engine ----------------
    async def test_06_audia_ai_recommendations_with_reasons(self):
        """Verifies Audia AI recommendation engine returns meaningful explanations."""
        test_uid = 999999999999999999
        prof = self.autoplay_service.get_user_profile(test_uid)
        prof.artist_affinity["Arijit Singh"] = 8.5
        prof.genre_affinity["Bollywood Romantic"] = 9.0
        prof.manual_language = "Hindi"

        recs = await self.autoplay_service.get_recommendations_for_user(test_uid, limit=4)
        self.assertIsInstance(recs, list)
        self.assertGreater(len(recs), 0)

        for rec in recs:
            self.assertIn("title", rec)
            self.assertIn("artist", rec)
            self.assertIn("reason", rec)
            # Verify explanation is meaningful and non-empty
            self.assertIsInstance(rec["reason"], str)
            self.assertGreater(len(rec["reason"]), 10)

    # ---------------- 6. Global Radio Directory Integration ----------------
    async def test_07_radio_directory_queries(self):
        """Verifies country, genre, and popular station discovery."""
        countries = self.radio_service.get_countries()
        self.assertIsInstance(countries, list)

        genres = self.radio_service.get_top_tags(limit=10)
        self.assertIsInstance(genres, list)
        self.assertGreaterEqual(len(genres), 5)

        # Test local country station search
        stations = self.radio_service.get_country_stations("India", limit=5)
        self.assertIsInstance(stations, list)

    # ---------------- 7. Listening History & Analytics Calculations ----------------
    async def test_08_listening_history_and_analytics(self):
        """Verifies real database writes for listening history and analytics calculations."""
        uid = 999999999999999999
        gid = self.mock_guild1.id

        # Clean any leftover rows from previous runs
        await db.execute("DELETE FROM listening_history WHERE discord_user_id = $1", uid)

        # Insert 3 test tracks into history
        await db.execute(
            """
            INSERT INTO listening_history (guild_id, discord_user_id, track_title, track_author, track_url, duration, platform)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            gid, uid, "Kesariya", "Arijit Singh", "https://youtube.com/watch?v=1", 268, "youtube"
        )
        await db.execute(
            """
            INSERT INTO listening_history (guild_id, discord_user_id, track_title, track_author, track_url, duration, platform)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            gid, uid, "Chaleya", "Arijit Singh", "https://youtube.com/watch?v=2", 200, "youtube"
        )
        await db.execute(
            """
            INSERT INTO listening_history (guild_id, discord_user_id, track_title, track_author, track_url, duration, platform)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            gid, uid, "Radio Mirchi 98.3", "Radio Mirchi", "https://radio.stream/mirchi", 1800, "radio"
        )

        # Query history
        hist = await db.fetch("SELECT * FROM listening_history WHERE discord_user_id = $1 ORDER BY played_at DESC", uid)
        self.assertEqual(len(hist), 3)

        # Check total calculations
        total_row = await db.fetchrow(
            "SELECT COUNT(*) as count, SUM(duration) as total_sec FROM listening_history WHERE discord_user_id = $1",
            uid
        )
        self.assertEqual(total_row["count"], 3)
        self.assertEqual(total_row["total_sec"], 2268)

        # Check top artist calculation
        top_art = await db.fetch(
            "SELECT track_author, COUNT(*) as plays FROM listening_history WHERE discord_user_id = $1 GROUP BY track_author ORDER BY plays DESC",
            uid
        )
        self.assertEqual(top_art[0]["track_author"], "Arijit Singh")
        self.assertEqual(top_art[0]["plays"], 2)

    # ---------------- 8. Custom Playlists & Library Favorites ----------------
    async def test_09_custom_playlists_and_favorites(self):
        """Verifies bookmarking favorites and custom playlist creation."""
        uid = 999999999999999999

        # Clean leftover test data
        await db.execute("DELETE FROM user_favorites WHERE discord_user_id = $1", uid)
        await db.execute("DELETE FROM user_playlists WHERE discord_user_id = $1", uid)

        # Add favorite
        await db.execute(
            """
            INSERT INTO user_favorites (discord_user_id, item_type, item_id, title, subtitle)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (discord_user_id, item_type, item_id) DO NOTHING;
            """,
            uid, "song", "test_song_1", "Tum Hi Ho", "Arijit Singh"
        )

        favs = await db.fetch("SELECT * FROM user_favorites WHERE discord_user_id = $1", uid)
        self.assertGreaterEqual(len(favs), 1)
        self.assertEqual(favs[0]["title"], "Tum Hi Ho")

        # Create custom playlist
        await db.execute(
            "INSERT INTO user_playlists (discord_user_id, name, description) VALUES ($1, $2, $3)",
            uid, "Late Night Chill", "Best relaxed late-night songs"
        )
        playlists = await db.fetch("SELECT * FROM user_playlists WHERE discord_user_id = $1", uid)
        self.assertGreaterEqual(len(playlists), 1)
        self.assertEqual(playlists[0]["name"], "Late Night Chill")

if __name__ == "__main__":
    unittest.main()
