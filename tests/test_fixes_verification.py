import unittest
import discord
from utils.emojis import Emojis, EmojiPartials, format_discord_emojis, VERIFIED_BOT_EMOJI_IDS
from cogs.music import make_error_embed, make_success_embed, AutoPlayControlCenterView, GuildMusicQueue

class DummyUser:
    def __init__(self, uid=12345):
        self.id = uid
        self.name = "TestUser"
        self.display_name = "TestUser"

class TestFixesVerification(unittest.TestCase):
    def test_verified_emojis(self):
        # All 19 user-specified emojis + syncwarning
        expected_emojis = {
            1559661648011075664,  # playing (animated)
            1559185207033077901,  # member
            1558918719881740490,  # Radio
            1558918836303044688,  # syncinkmusic
            1571879222908031078,  # Audia_AI
            1558019502019575918,  # approved (animated)
            1558019488408932423,  # refused (animated)
            1559660676853797005,  # like
            1559660727373930657,  # dislike
            1558917288621777016,  # NextTrack
            1558913195119222814,  # PlayButton
            1558917154294997062,  # Previous
            1558913299221979289,  # pause
            1558916019089575936,  # queue
            1558915041896562860,  # queue_add
            1558916635866308719,  # repeat
            1558914298544136192,  # shuffle
            1568355166913167430,  # scale
            1558918533214380243,  # delete
            1520914584012328961,  # syncwarning (animated)
        }
        for eid in expected_emojis:
            self.assertIn(eid, VERIFIED_BOT_EMOJI_IDS, f"Missing verified emoji ID: {eid}")

        self.assertEqual(Emojis.PLAYING, "<a:playing:1559661648011075664>")
        self.assertEqual(Emojis.WARNING, "<a:syncwarning:1520914584012328961>")
        self.assertEqual(Emojis.ALERT, "<a:syncwarning:1520914584012328961>")
        self.assertEqual(Emojis.MEMBER, "<:member:1559185207033077901>")
        self.assertEqual(Emojis.RADIO, "<:Radio:1558918719881740490>")
        self.assertEqual(Emojis.SYNCINK_MUSIC, "<:syncinkmusic:1558918836303044688>")
        self.assertEqual(Emojis.AUDIA_AI, "<:Audia_AI:1571879222908031078>")
        self.assertEqual(Emojis.APPROVED, "<a:approved:1558019502019575918>")
        self.assertEqual(Emojis.REFUSED, "<a:refused:1558019488408932423>")
        self.assertEqual(Emojis.LIKE, "<:like:1559660676853797005>")
        self.assertEqual(Emojis.DISLIKE, "<:dislike:1559660727373930657>")
        self.assertEqual(Emojis.NEXT, "<:NextTrack:1558917288621777016>")
        self.assertEqual(Emojis.PLAY_BUTTON, "<:PlayButton:1558913195119222814>")
        self.assertEqual(Emojis.PREVIOUS, "<:Previous:1558917154294997062>")
        self.assertEqual(Emojis.PAUSE_BUTTON, "<:pause:1558913299221979289>")
        self.assertEqual(Emojis.QUEUE, "<:queue:1558916019089575936>")
        self.assertEqual(Emojis.QUEUE_ADD, "<:queue_add:1558915041896562860>")
        self.assertEqual(Emojis.REPEAT, "<:repeat:1558916635866308719>")
        self.assertEqual(Emojis.SHUFFLE, "<:shuffle:1558914298544136192>")
        self.assertEqual(Emojis.SCALE, "<:scale:1568355166913167430>")
        self.assertEqual(Emojis.DELETE, "<:delete:1558918533214380243>")

        self.assertEqual(EmojiPartials.PLAYING.id, 1559661648011075664)
        self.assertTrue(EmojiPartials.PLAYING.animated)
        self.assertEqual(EmojiPartials.WARNING.id, 1520914584012328961)
        self.assertTrue(EmojiPartials.WARNING.animated)
        self.assertEqual(EmojiPartials.PLAY_BUTTON.id, 1558913195119222814)
        self.assertEqual(EmojiPartials.PAUSE_BUTTON.id, 1558913299221979289)
        self.assertEqual(EmojiPartials.PREVIOUS.id, 1558917154294997062)
        self.assertEqual(EmojiPartials.NEXT.id, 1558917288621777016)
        self.assertEqual(EmojiPartials.DELETE.id, 1558918533214380243)
        self.assertEqual(EmojiPartials.QUEUE.id, 1558916019089575936)

    def test_format_discord_emojis_replacements(self):
        # Broken emoji replaced
        raw_broken = "<a:1573698286941118705> Left the voice channel"
        formatted = format_discord_emojis(raw_broken)
        self.assertIn("<a:syncwarning:1520914584012328961>", formatted)

        # 🎶 replaced with animated playing
        raw_music = "🎶 Now Playing"
        formatted_music = format_discord_emojis(raw_music)
        self.assertIn("<a:playing:1559661648011075664>", formatted_music)

    def test_format_discord_emojis_no_double_nesting(self):
        # 1. Ensure existing valid tag is never corrupted by substring replacement
        valid_tag = "<a:syncwarning:1520914584012328961> Left the voice channel due to empty queue"
        formatted = format_discord_emojis(valid_tag)
        self.assertEqual(formatted, valid_tag)
        self.assertNotIn("<a<a:", formatted)
        self.assertNotIn("1520914584012328961> Left", formatted.replace("<a:syncwarning:1520914584012328961> Left", ""))

        # 2. Clean up corrupted double tag
        corrupted = "<a<a:syncwarning:1520914584012328961>:1520914584012328961> Left the voice channel"
        cleaned = format_discord_emojis(corrupted)
        self.assertEqual(cleaned, "<a:syncwarning:1520914584012328961> Left the voice channel")

        # 3. Clean up broken <a ! 1520914584012328961>
        malformed = "<a ! 1520914584012328961> Left the voice channel"
        cleaned_m = format_discord_emojis(malformed)
        self.assertEqual(cleaned_m, "<a:syncwarning:1520914584012328961> Left the voice channel")

    def test_music_player_layout_view(self):
        from cogs.music import MusicPlayerLayoutView, Track
        queue = GuildMusicQueue(guild_id=999999)
        track = Track(
            title="The 1975 - About You",
            clean_title="The 1975 - About You",
            author="The 1975",
            duration=327,
            url="https://youtube.com/watch?v=123",
            stream_url="https://example.com/stream",
            thumbnail="https://example.com/thumb.jpg",
            platform="youtube",
            requested_by=DummyUser(77777)
        )
        queue.current_track = track

        view = MusicPlayerLayoutView(music_cog=None, queue=queue)
        self.assertIsInstance(view, discord.ui.LayoutView)
        self.assertEqual(len(view.children), 1)  # Container

        container = view.children[0]
        self.assertIsInstance(container, discord.ui.Container)
        # Verify children inside container: Section, ActionRow (5 buttons), Separator, TextDisplay (footer)
        items = container.children
        self.assertEqual(len(items), 4)

        sec = items[0]
        self.assertIsInstance(sec, discord.ui.Section)
        self.assertIn(f"{Emojis.PLAYING} Now Playing", sec.children[0].content)

        row = items[1]
        self.assertIsInstance(row, discord.ui.ActionRow)
        self.assertEqual(len(row.children), 5)  # Pause/Resume, Prev, Skip, Stop, Queue
        for btn in row.children:
            self.assertIsInstance(btn, discord.ui.Button)
            self.assertIsNone(btn.label)  # Icon-only! No text labels!

        # Stop button must be danger style
        self.assertEqual(view.btn_stop.style, discord.ButtonStyle.danger)

        sep = items[2]
        self.assertIsInstance(sep, discord.ui.Separator)

        footer = items[3]
        self.assertIsInstance(footer, discord.ui.TextDisplay)
        self.assertIn(f"{Emojis.MEMBER} Track requested by <@77777>", footer.content)

        # Now test with AutoPlay active
        queue.autoplay = True
        view_ap = MusicPlayerLayoutView(music_cog=None, queue=queue)
        items_ap = view_ap.children[0].children
        self.assertEqual(len(items_ap), 5)  # Sec, Row 1, Row 2 (Like/Dislike), Sep, Footer
        row2 = items_ap[2]
        self.assertIsInstance(row2, discord.ui.ActionRow)
        self.assertEqual(len(row2.children), 2)
        self.assertEqual(row2.children[0].label, "Like")
        self.assertEqual(row2.children[0].emoji, EmojiPartials.LIKE)
        self.assertEqual(row2.children[1].label, "Dislike")
        self.assertEqual(row2.children[1].emoji, EmojiPartials.DISLIKE)

        footer_ap = items_ap[4]
        self.assertIn("Audia AI AutoPlay Active", footer_ap.content)
        self.assertIn(Emojis.AUDIA_AI, footer_ap.content)

    def test_no_embed_footers(self):
        err_embed = make_error_embed("Something went wrong")
        self.assertIsNone(err_embed.footer.text)

        succ_embed = make_success_embed("Completed successfully")
        self.assertIsNone(succ_embed.footer.text)

    def test_autoplay_view_instantiation_no_v2_error(self):
        queue = GuildMusicQueue(guild_id=999999)
        user = DummyUser(12345)
        # Should instantiate smoothly without raising "v2 items cannot be added to this view"
        view = AutoPlayControlCenterView(music_cog=None, user=user, queue=queue)
        self.assertIsInstance(view, discord.ui.View)
        self.assertEqual(len(view.children), 7)  # mood_select, lang_select, disc_select, toggle, block, unblock, profile
        embed = view.build_embed()
        self.assertIsNone(embed.footer.text)

    def test_emoji_manager_preserves_verified_emojis(self):
        from utils.emoji_manager import EmojiManager
        for norm, d in EmojiManager.DEFAULT_KNOWN_EMOJIS.items():
            self.assertIn(d["id"], VERIFIED_BOT_EMOJI_IDS)

    def test_server_voice_latency_serialization(self):
        from services.web.websocket import DashboardWebSocketManager
        mgr = DashboardWebSocketManager.get_instance()
        data = mgr.serialize_guild_playback(110000000000000001, None)
        self.assertIn("voice_latency", data)
        self.assertIn("latency_ms", data)
        self.assertEqual(data["voice_latency"], 18.5)

    def test_unblock_artist_discord_and_history_db_import(self):
        import inspect
        import cogs.music as music_mod
        from cogs.music import AutoPlayUnblockView, build_now_playing_embed
        from services.autoplay_service import AutoPlayService

        ap = AutoPlayService.get_instance()
        uid = 999888777666111
        try:
            ap.block_artist(uid, "Blocked Test Artist")
            view = AutoPlayUnblockView(uid)
            # First item is Select dropdown with the blocked artist
            select_items = [c for c in view.children if isinstance(c, discord.ui.Select)]
            self.assertEqual(len(select_items), 1)
            self.assertEqual(select_items[0].options[0].value, "Blocked Test Artist")

            ok, _, rem = ap.unblock_artist(uid, "blocked test artist")
            self.assertTrue(ok)
            self.assertEqual(rem, [])
        finally:
            ap._profiles.pop(uid, None)
            ap.save_profiles()

        # Verify build_now_playing_embed has Support Bot style platform footer & play_track imports db
        q = GuildMusicQueue(guild_id=999999)
        empty_emb = build_now_playing_embed(q)
        self.assertEqual(empty_emb.footer.text, "SyncInk Platform")
        play_src = inspect.getsource(music_mod.Music.play_track)
        self.assertIn("from database import db", play_src)

    def test_artwork_service_and_discord_clyde_svg(self):
        from pathlib import Path
        from services.artwork_service import is_fallback_artwork, extract_youtube_poster

        self.assertTrue(is_fallback_artwork(None))
        self.assertTrue(is_fallback_artwork(""))
        self.assertTrue(is_fallback_artwork("https://files.catbox.moe/74l9su.png"))
        self.assertTrue(is_fallback_artwork("static/radio-bot.jpg"))
        self.assertTrue(is_fallback_artwork("static/syncink-main.jpg"))
        self.assertTrue(is_fallback_artwork("https://syncink.site/dashboard/radio/static/radio-bot.jpg"))
        self.assertTrue(is_fallback_artwork("https://syncink.site/dashboard/radio/static/syncink-main.jpg"))
        self.assertFalse(is_fallback_artwork("https://is1-ssl.mzstatic.com/image/thumb/cover/600x600bb.jpg"))

        self.assertEqual(
            extract_youtube_poster("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
        )
        self.assertEqual(
            extract_youtube_poster("https://youtu.be/dQw4w9WgXcQ"),
            "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
        )
        self.assertIsNone(extract_youtube_poster("https://open.spotify.com/track/123"))

        static_dir = Path(__file__).resolve().parent.parent / "static"
        self.assertTrue((static_dir / "radio-bot.jpg").exists(), "Missing static/radio-bot.jpg")
        self.assertTrue((static_dir / "syncink-main.jpg").exists(), "Missing static/syncink-main.jpg")
        index_html = (static_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("static/syncink-main.jpg", index_html)
        for page in ("index.html", "status.html", "guide.html", "faq.html", "privacy.html", "terms.html"):
            html = (static_dir / page).read_text(encoding="utf-8")
            self.assertIn("static/radio-bot.jpg", html, f"{page} missing radio-bot.jpg brand logo")
            self.assertIn("M8.02 15.33", html, f"{page} missing full Discord Clyde eye cutout path")
            self.assertIn('fill-rule="evenodd"', html, f"{page} missing fill-rule='evenodd' on Discord SVG")

    def test_all_cog_commands_and_audia_replay_fixes(self):
        """Verifies /audia no longer fails with 'Command' object is not callable, /replay has single response, and fast stream reuse works."""
        import asyncio
        import time
        from unittest.mock import AsyncMock, MagicMock
        import cogs.music as music_mod
        import cogs.help as help_mod
        import cogs.spotify as spotify_mod
        from services.music_service import MusicService, Track

        mock_bot = MagicMock()
        mock_bot.user = MagicMock()
        mock_bot.user.id = 1500567606648897819
        mock_bot.loop = asyncio.new_event_loop()

        try:
            music_cog = music_mod.Music(mock_bot)
            help_cog = help_mod.Help(mock_bot)
            spotify_cog = spotify_mod.Spotify(mock_bot)

            # Verify every slash and prefix command attribute exists cleanly
            expected_music_cmds = [
                "slash_play", "slash_radio", "slash_lofi", "slash_search", "slash_pause",
                "slash_resume", "slash_skip", "slash_previous", "slash_stop", "slash_leave",
                "slash_queue", "slash_remove", "slash_np", "slash_shuffle", "slash_loop",
                "slash_volume", "slash_audia", "slash_autoplay", "slash_247", "slash_replay",
                "slash_invite",
                "cmd_play", "cmd_radio", "cmd_lofi", "cmd_search", "cmd_pause", "cmd_resume",
                "cmd_skip", "cmd_previous", "cmd_stop", "cmd_leave", "cmd_queue", "cmd_remove",
                "cmd_np", "cmd_shuffle", "cmd_loop", "cmd_volume", "cmd_autoplay", "cmd_247",
                "cmd_replay", "cmd_invite",
            ]
            for name in expected_music_cmds:
                self.assertTrue(hasattr(music_cog, name), f"Missing Music command {name}")

            self.assertTrue(hasattr(help_cog, "help"))
            self.assertTrue(hasattr(help_cog, "slash_help"))
            self.assertTrue(hasattr(spotify_cog, "spotify_group"))

            async def _run_command_checks():
                # 1. Verify /audia (interactive menu + mode='on' + mode='off') executes without TypeError
                for mode_val in ("on", "off", None):
                    inter = MagicMock(spec=discord.Interaction)
                    inter.guild_id = 999888111
                    inter.user = DummyUser(777666)
                    inter.response = MagicMock()
                    inter.response.is_done = MagicMock(return_value=False)
                    inter.response.send_message = AsyncMock()
                    inter.followup = MagicMock()
                    inter.followup.send = AsyncMock()

                    await music_cog.slash_audia.callback(music_cog, inter, mode=mode_val)
                    self.assertTrue(inter.response.send_message.await_count == 1)

                # 2. Verify /replay sends single response and stops once with manual_skip=True
                q = music_cog.service.get_queue(999888111)
                q.tracks.clear()
                q.current_track = Track(
                    title="Fast Replay Test",
                    clean_title="Fast Replay Test",
                    author="Artist",
                    duration=180,
                    url="https://youtube.com/watch?v=dQw4w9WgXcQ",
                    stream_url="https://rr1.googlevideo.com/videoplayback?id=123",
                    thumbnail="static/radio-bot.jpg",
                    platform="youtube",
                    requested_by=DummyUser(777666),
                    _stream_resolved_at=time.time(),
                )
                q.voice_client = MagicMock()
                q.voice_client.stop = MagicMock()

                replay_inter = MagicMock(spec=discord.Interaction)
                replay_inter.guild_id = 999888111
                replay_inter.user = DummyUser(777666)
                replay_inter.response = MagicMock()
                replay_inter.response.is_done = MagicMock(return_value=False)
                replay_inter.response.send_message = AsyncMock()
                await music_cog.slash_replay.callback(music_cog, replay_inter)
                self.assertEqual(q.voice_client.stop.call_count, 1)
                self.assertEqual(replay_inter.response.send_message.await_count, 1)
                self.assertTrue(q.manual_skip)

                # 3. Verify fresh single-pass stream URL skips redundant yt-dlp round-trip
                svc = MusicService.get_instance()
                cached_url = await svc.refresh_stream_url(q.current_track)
                self.assertEqual(cached_url, "https://rr1.googlevideo.com/videoplayback?id=123")

            mock_bot.loop.run_until_complete(_run_command_checks())

            # 4. Verify ensure_voice uses 'interaction' (no ctx NameError) and ensure_voice_ctx connects when vc is None
            import inspect
            ev_src = inspect.getsource(music_mod.Music.ensure_voice)
            self.assertNotIn("send_error_embed(\n                        ctx", ev_src)
            evc_src = inspect.getsource(music_mod.Music.ensure_voice_ctx)
            self.assertIn("        vc = await channel.connect(", evc_src)
        finally:
            mock_bot.loop.close()


if __name__ == "__main__":
    unittest.main()
