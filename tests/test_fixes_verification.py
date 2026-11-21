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
