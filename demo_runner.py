import asyncio
import os
import sys
import time
import datetime
from unittest.mock import MagicMock
from database import db
from services.web.server import UnifiedWebServer
from services.web.auth import DashboardAuthManager
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("SyncInkDemo")


async def seed_demo_data():
    """Seeds sample favorites, listening history, and custom playlist for demo user 999888777."""
    uid = 999888777
    gid = 110000000000000001

    # 1. User preferences
    await db.execute(
        """
        INSERT INTO user_preferences (discord_user_id, timezone, language, private_listening, theme)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (discord_user_id) DO NOTHING;
        """,
        uid, "UTC", "en", False, "dark"
    )

    # 2. Favorites
    sample_favs = [
        ("song", "fav_1", "Midnight City Vibes", "Lofi Fruit & Chill"),
        ("song", "fav_2", "Golden Hour", "JVKE"),
        ("song", "fav_3", "Starboy", "The Weeknd ft. Daft Punk"),
        ("radio", "fav_4", "Radio Mirchi 98.3 FM", "Top Bollywood Hits"),
        ("radio", "fav_5", "Anime J-Pop FM", "Tokyo Live"),
        ("artist", "fav_6", "Arijit Singh", "Bollywood Acoustic"),
        ("artist", "fav_7", "Anuv Jain", "Indie Folk"),
    ]
    for itype, iid, title, subtitle in sample_favs:
        await db.execute(
            """
            INSERT INTO user_favorites (discord_user_id, item_type, item_id, title, subtitle)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (discord_user_id, item_type, item_id) DO NOTHING;
            """,
            uid, itype, iid, title, subtitle
        )

    # 3. Custom Playlist
    existing_pl = await db.fetch("SELECT id FROM user_playlists WHERE discord_user_id = $1", uid)
    if not existing_pl:
        await db.execute(
            "INSERT INTO user_playlists (discord_user_id, name, description) VALUES ($1, $2, $3)",
            uid, "Cyber Chill Sessions", "Curated downtempo, lo-fi beats, and late-night indie."
        )

    # 4. Listening History with varied timestamps for realistic analytics
    hist_count = await db.fetchrow("SELECT COUNT(*) as c FROM listening_history WHERE discord_user_id = $1", uid)
    if not hist_count or hist_count["c"] < 5:
        tracks = [
            ("Midnight City Vibes", "Lofi Fruit & Chill", 210, "youtube", 1),
            ("Coffee Shop Rain", "Chillhop Music", 185, "youtube", 3),
            ("Golden Hour", "JVKE", 209, "youtube", 5),
            ("Radio Mirchi 98.3 FM", "Radio Mirchi", 1800, "radio", 8),
            ("Choo Lo", "The Local Train", 234, "youtube", 12),
            ("Baarishein", "Anuv Jain", 215, "youtube", 15),
            ("Anime J-Pop FM", "Tokyo Live Radio", 2400, "radio", 19),
            ("Starboy", "The Weeknd", 230, "youtube", 22),
            ("Kesariya", "Arijit Singh", 268, "youtube", 26),
            ("Softly", "Karan Aujla", 195, "youtube", 30),
        ]
        now = datetime.datetime.utcnow()
        for title, artist, duration, platform, hours_ago in tracks:
            played_at = now - datetime.timedelta(hours=hours_ago)
            await db.execute(
                """
                INSERT INTO listening_history (guild_id, discord_user_id, track_title, track_author, track_url, duration, platform, played_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                gid, uid, title, artist, "https://youtube.com", duration, platform, played_at
            )

    # 5. Create active demo session for seamless preview
    auth_mgr = DashboardAuthManager.get_instance()
    demo_user = {
        "id": str(uid),
        "username": "SyncInk Listener",
        "discriminator": "0001",
        "avatar": None,
        "email": "demo@syncink.site"
    }
    demo_token = {"access_token": "demo_preview_token", "expires_in": 7 * 86400}
    session_id = await auth_mgr.create_session(demo_user, demo_token)
    return session_id


async def main():
    port = int(os.getenv("PORT") or 8888)
    host = "127.0.0.1"

    await db.connect()
    session_id = await seed_demo_data()

    # Mock Bot for dashboard standalone preview
    mock_bot = MagicMock()
    mock_bot.user = MagicMock()
    mock_bot.user.id = 123456789
    mock_bot.user.name = "SyncInk Radio"
    mock_bot.guilds = []

    server = UnifiedWebServer(port=port, host=host, bot=mock_bot)
    await server.start()

    log.info("=" * 70)
    log.info("🌟 SYNCINK RADIO DEMO SERVER IS LIVE!")
    log.info(f"🌐 Access URL: http://{host}:{port}")
    log.info("✨ Demo Mode: Activated with rich sample servers, Audia AI, and stats.")
    log.info("=" * 70)

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutting down demo server...")
        await server.stop()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
