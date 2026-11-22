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
        self.assertIn("Audia AI Active", footer_ap.content)
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
        self.assertEqual(len(view.children), 6)  # mood_select, lang_select, disc_select, toggle, block, profile
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

if __name__ == "__main__":
    unittest.main()
