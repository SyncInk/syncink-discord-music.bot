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
        self.assertIn(1559661648011075664, VERIFIED_BOT_EMOJI_IDS)
        self.assertIn(1520914584012328961, VERIFIED_BOT_EMOJI_IDS)

        self.assertEqual(Emojis.PLAYING, "<a:playing:1559661648011075664>")
        self.assertEqual(Emojis.WARNING, "<a:syncwarning:1520914584012328961>")
        self.assertEqual(Emojis.ALERT, "<a:syncwarning:1520914584012328961>")

        self.assertEqual(EmojiPartials.PLAYING.id, 1559661648011075664)
        self.assertTrue(EmojiPartials.PLAYING.animated)
        self.assertEqual(EmojiPartials.WARNING.id, 1520914584012328961)
        self.assertTrue(EmojiPartials.WARNING.animated)

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
        self.assertIn("💿 Now Playing", sec.children[0].content)

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
        self.assertIn("👤 Track requested by <@77777>", footer.content)

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

if __name__ == "__main__":
    unittest.main()
