import discord
from discord.ext import commands
from discord import app_commands
from utils.ui import SyncInkEmbed, BRAND_ACCENT, ERROR_COLOR
from utils.emojis import Emojis, EmojiPartials

HELP_COLOR = discord.Color(0x7b2cbf)  # SyncInk Cyber Violet

class HelpCategorySelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(
            placeholder="⚙️ Select a command category",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        view: HelpPaginationView = self.view
        selected_index = int(self.values[0])
        await view.set_page(interaction, selected_index)


class HelpPaginationView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], author_id: int, select_options: list[discord.SelectOption]):
        super().__init__(timeout=180)
        self.pages = pages
        self.author_id = author_id
        self.current_page = 0
        self.select_menu = HelpCategorySelect(select_options)
        self.add_item(self.select_menu)
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = (self.current_page == 0)
        self.next_btn.disabled = (self.current_page == len(self.pages) - 1)
        self.page_indicator.label = f"Page {self.current_page + 1}/{len(self.pages)}"
        
        for opt in self.select_menu.options:
            if self.current_page == 0:
                opt.default = False
            else:
                opt.default = (opt.value == str(self.current_page))

    async def set_page(self, interaction: discord.Interaction, page_idx: int):
        self.current_page = page_idx
        self._update_buttons()
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, custom_id="help_prev", row=1)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="Page 1/1", style=discord.ButtonStyle.primary, disabled=True, custom_id="help_indicator", row=1)
    async def page_indicator(self, interaction: discord.Interaction, button: discord.ui.Button):
        pass

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="help_next", row=1)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            embed = discord.Embed(
                description=f"### {Emojis.WARNING} Use `/help` or `?help` to open your own guide!",
                color=0xFEE75C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True


class Help(commands.Cog):
    """Categorized command guide with interactive dropdown and pagination for SyncInk Radio."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _build_overview_page(self, categories: list[tuple[str, str, str]], total_pages: int) -> discord.Embed:
        embed = discord.Embed(
            title=f"{Emojis.SYNCINK_MUSIC} SyncInk Radio Guide",
            color=HELP_COLOR
        )
        desc_lines = [
            "Welcome to the official **SyncInk Radio & Music Bot**.\n",
            "High-fidelity 48kHz Opus streaming, 24/7 world radio, AI AutoPlay, and interactive player card.\n",
            "Commands support both Discord `/` slash commands and `?` prefix invocations.\n"
        ]
        for cat_emoji, cat_name, cat_desc in categories:
            desc_lines.append(f"{cat_emoji} **{cat_name}**\n╰ {cat_desc}\n")

        embed.description = "\n".join(desc_lines).strip()
        embed.set_footer(text=f"Page 1 of {total_pages} • SyncInk Platform", icon_url="https://files.catbox.moe/74l9su.png")
        return embed

    def _build_category_page(self, title_with_emoji: str, commands_list: list[tuple[str, str]], page_num: int, total_pages: int) -> discord.Embed:
        embed = discord.Embed(
            title=f"{title_with_emoji}",
            color=HELP_COLOR
        )
        lines = []
        for cmd_name, cmd_desc in commands_list:
            lines.append(f"**`{cmd_name}`**\n╰ {cmd_desc}\n")
        embed.description = "\n".join(lines).strip()
        embed.set_footer(text=f"Page {page_num} of {total_pages} • SyncInk Platform", icon_url="https://files.catbox.moe/74l9su.png")
        return embed

    def _get_help_data(self) -> tuple[list[tuple[str, str, str]], list[tuple[str, list[tuple[str, str]]]]]:
        categories_overview = [
            (Emojis.PLAY_BUTTON, "Playback & Streaming", "Play audio from YouTube, Spotify, and SoundCloud with instant playback controls."),
            (Emojis.QUEUE, "Queue & Audio Controls", "Manage queue order, real-time player card, shuffle, volume, and repeat modes."),
            (Emojis.RADIO, "24/7 Radio & AI AutoPlay", "Stream global live radio stations by country flag and configure personalized AI AutoPlay.")
        ]

        playback_cmds = [
            ("/play <query>", "Stream audio from YouTube, Spotify, or SoundCloud directly into voice."),
            ("/search <query>", "Interactively search and select from top 5 audio results."),
            ("/pause / /resume", "Pause or resume current playback."),
            ("/skip", "Skip currently playing track."),
            ("/previous", "Play previously played track."),
            ("/replay", "Restart current track from the beginning."),
            ("/stop / /leave", "Stop playback, clear queue, and disconnect bot from voice.")
        ]

        queue_cmds = [
            ("/queue", "Display current track queue with interactive pagination controls."),
            ("/nowplaying (/np)", "Display real-time player card with live progress bar and upcoming tracks."),
            ("/volume <1-150>", "Adjust audio playback volume."),
            ("/loop <off|track|queue>", "Toggle repeat mode for current track or entire queue."),
            ("/shuffle", "Randomly shuffle upcoming tracks in queue.")
        ]

        radio_cmds = [
            ("/radio [country] [station]", "Browse and stream 24/7 world live radio stations by country flag/name."),
            ("/lofi", "Instantly start 24/7 high-fidelity Lo-Fi beats streaming."),
            ("/autoplay", "Configure intelligent AI AutoPlay recommendations, genres, moods, and languages.")
        ]

        category_details = [
            (f"{Emojis.PLAY_BUTTON} Playback & Streaming", playback_cmds),
            (f"{Emojis.QUEUE} Queue & Audio Controls", queue_cmds),
            (f"{Emojis.RADIO} 24/7 Radio & AI AutoPlay", radio_cmds)
        ]

        return categories_overview, category_details

    @commands.command(name="help", description="Displays an interactive guide to all bot commands.")
    async def help(self, ctx: commands.Context):
        try:
            await ctx.message.delete()
        except Exception:
            pass

        cat_overview, cat_details = self._get_help_data()
        total_pages = len(cat_details) + 1

        pages = [self._build_overview_page(cat_overview, total_pages)]
        select_options = [
            discord.SelectOption(
                label="Overview",
                value="0",
                description="General bot introduction & features",
                emoji=EmojiPartials.QUESTION
            )
        ]

        emojis_list = [EmojiPartials.PLAY_BUTTON, EmojiPartials.QUEUE, EmojiPartials.RADIO]
        labels_list = ["Playback & Streaming", "Queue & Audio Controls", "24/7 Radio & AI AutoPlay"]
        descs_list = ["Play, search, skip, stop", "Queue, progress, volume, loop", "Global live radio and AI DJ"]

        for i, (cat_title, cmds) in enumerate(cat_details, start=1):
            pages.append(self._build_category_page(cat_title, cmds, i + 1, total_pages))
            select_options.append(
                discord.SelectOption(
                    label=labels_list[i - 1],
                    value=str(i),
                    description=descs_list[i - 1],
                    emoji=emojis_list[i - 1]
                )
            )

        view = HelpPaginationView(pages, ctx.author.id, select_options)
        await ctx.send(embed=pages[0], view=view)

    @app_commands.command(name="help", description="Displays an interactive guide to all bot commands.")
    async def slash_help(self, interaction: discord.Interaction):
        cat_overview, cat_details = self._get_help_data()
        total_pages = len(cat_details) + 1

        pages = [self._build_overview_page(cat_overview, total_pages)]
        select_options = [
            discord.SelectOption(
                label="Overview",
                value="0",
                description="General bot introduction & features",
                emoji=EmojiPartials.QUESTION
            )
        ]

        emojis_list = [EmojiPartials.PLAY_BUTTON, EmojiPartials.QUEUE, EmojiPartials.RADIO]
        labels_list = ["Playback & Streaming", "Queue & Audio Controls", "24/7 Radio & AI AutoPlay"]
        descs_list = ["Play, search, skip, stop", "Queue, progress, volume, loop", "Global live radio and AI DJ"]

        for i, (cat_title, cmds) in enumerate(cat_details, start=1):
            pages.append(self._build_category_page(cat_title, cmds, i + 1, total_pages))
            select_options.append(
                discord.SelectOption(
                    label=labels_list[i - 1],
                    value=str(i),
                    description=descs_list[i - 1],
                    emoji=emojis_list[i - 1]
                )
            )

        view = HelpPaginationView(pages, interaction.user.id, select_options)
        await interaction.response.send_message(embed=pages[0], view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
