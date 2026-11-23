import asyncio
import os
import aiohttp
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, List, Dict, Any

from utils.logger import log
from utils.emojis import Emojis, EmojiPartials, format_discord_emojis
from services.spotify.client import SpotifyClient
from services.spotify.auth import SpotifyUserAuthManager
from services.spotify.resolver import SpotifyResolver
from services.music_service import MusicService, clean_title, Track
from database import db

BRAND_COLOR = 0x7b2cbf  # SyncInk Cyber Violet
SPOTIFY_COLOR = 0x1DB954  # Spotify Green

class SpotifyConnectView(discord.ui.View):
    def __init__(self, auth_url: str):
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.Button(
                label="Connect Spotify Account",
                url=auth_url,
                emoji=EmojiPartials.SPOTIFY,
                style=discord.ButtonStyle.link
            )
        )

class SpotifyPlaylistsSelect(discord.ui.Select):
    def __init__(self, playlists: List[Dict[str, Any]], music_cog: Any):
        self.music_cog = music_cog
        self.playlist_map = {p["id"]: p for p in playlists}
        options = []
        for p in playlists[:25]:
            name = (p.get("name") or "Untitled Playlist")[:90]
            desc = f"{p.get('tracks', {}).get('total', 0)} tracks"
            options.append(
                discord.SelectOption(
                    label=name,
                    value=p["id"],
                    description=desc,
                    emoji=EmojiPartials.SPOTIFY
                )
            )
        super().__init__(placeholder="Select a Spotify playlist to play...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        playlist_id = self.values[0]

        vc = await self.music_cog.ensure_voice(interaction)
        if not vc:
            return

        queue = self.music_cog.service.get_queue(interaction.guild_id)
        queue.voice_client = vc
        queue.text_channel = interaction.channel

        if str(playlist_id).startswith("syncink_"):
            try:
                raw_pk = int(str(playlist_id).replace("syncink_", ""))
                rows = await db.fetch("""
                    SELECT title, author, url, duration, thumbnail, platform
                    FROM user_playlist_tracks
                    WHERE playlist_id = $1
                    ORDER BY position ASC;
                """, raw_pk)
                if not rows:
                    await interaction.followup.send(
                        embed=discord.Embed(description=f"### {Emojis.WARNING} This library playlist is currently empty.", color=0xFEE75C),
                        ephemeral=True
                    )
                    return
                tracks = [
                    Track(
                        title=r["title"],
                        clean_title=clean_title(r["title"]),
                        author=r["author"] or "Unknown Artist",
                        duration=int(r["duration"] or 0),
                        url=r["url"],
                        stream_url="",
                        thumbnail=r["thumbnail"],
                        platform=r["platform"] or "spotify",
                        requested_by=interaction.user,
                        is_live=False
                    )
                    for r in rows
                ]
                await self.music_cog.enqueue_and_play(interaction, tracks)
            except Exception as e:
                log.error(f"[SyncInk Playlist Play Error] {e}")
                await interaction.followup.send(
                    embed=discord.Embed(description=f"### {Emojis.REFUSED} Error loading playlist: `{e}`", color=0xED4245),
                    ephemeral=True
                )
            return

        playlist_data = self.playlist_map.get(playlist_id, {})
        playlist_url = playlist_data.get("url") or playlist_data.get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{playlist_id}")

        try:
            tracks = await self.music_cog.service.search_and_extract(playlist_url, interaction.user, platform="spotify", limit=100)
            if not tracks:
                await interaction.followup.send(
                    embed=discord.Embed(description=f"### {Emojis.WARNING} Could not load tracks from selected playlist.", color=0xFEE75C),
                    ephemeral=True
                )
                return

            await self.music_cog.enqueue_and_play(interaction, tracks)
        except Exception as e:
            log.error(f"[Spotify Playlist Play Error] {e}")
            await interaction.followup.send(
                embed=discord.Embed(description=f"### {Emojis.REFUSED} Error loading playlist: `{e}`", color=0xED4245),
                ephemeral=True
            )

class SpotifyAddPlaylistModal(discord.ui.Modal, title="Add Public Spotify Playlist"):
    url_input = discord.ui.TextInput(
        label="Spotify Playlist Link",
        placeholder="https://open.spotify.com/playlist/...",
        required=True,
        max_length=300
    )

    def __init__(self, music_cog: Any):
        super().__init__()
        self.music_cog = music_cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        url = self.url_input.value.strip()
        auth_mgr = SpotifyUserAuthManager.get_instance()
        pl = await auth_mgr.add_user_spotify_playlist(interaction.user.id, url)
        if not pl:
            await interaction.followup.send(
                embed=discord.Embed(
                    description=format_discord_emojis(f"### {Emojis.WARNING} Could not load Spotify playlist. Please ensure the playlist link is public and valid."),
                    color=0xFEE75C
                ),
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"{Emojis.CHECK_YES} Added Spotify Playlist to Library",
            description=format_discord_emojis(
                f"**[{pl['name']}]({pl['url']})**\n\n"
                f"• Tracks: **{pl['tracks_total']}**\n"
                f"• Platform: Spotify\n\n"
                f"-# You can now stream it anytime with `/spotify playlists` or from the Web Dashboard!"
            ),
            color=SPOTIFY_COLOR
        )
        if pl.get("image_url"):
            embed.set_thumbnail(url=pl["image_url"])
        await interaction.followup.send(embed=embed, ephemeral=True)

class SpotifyPlaylistsView(discord.ui.View):
    def __init__(self, playlists: List[Dict[str, Any]], music_cog: Any):
        super().__init__(timeout=180)
        self.music_cog = music_cog
        if playlists:
            self.add_item(SpotifyPlaylistsSelect(playlists, music_cog))

    @discord.ui.button(label="Add Public Playlist", emoji=EmojiPartials.QUEUE_ADD, style=discord.ButtonStyle.secondary, row=1)
    async def add_playlist_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SpotifyAddPlaylistModal(self.music_cog))


class Spotify(commands.Cog):
    """
    Official Spotify account integration, PKCE OAuth linking,
    personal playlist streaming, and metadata inspection.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auth_mgr = SpotifyUserAuthManager.get_instance()
        self.client = SpotifyClient.get_instance()

    spotify_group = app_commands.Group(
        name="spotify",
        description="Spotify account connection and playlist streaming controls."
    )

    # ─────────────────────────────────────────────────────────────
    # Slash Commands: /spotify
    # ─────────────────────────────────────────────────────────────

    @spotify_group.command(name="connect", description="Securely link your personal Spotify account to SyncInk Radio.")
    async def slash_spotify_connect(self, interaction: discord.Interaction):
        if not self.client.is_configured:
            embed = discord.Embed(
                description=format_discord_emojis(
                    f"### {Emojis.WARNING} Spotify Integration Temporarily Unavailable\n\n"
                    "The Spotify connection service is currently unavailable. Please try again later."
                ),
                color=0xFEE75C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        try:
            auth_url, state = await self.auth_mgr.generate_auth_url(interaction.user.id)
            view = SpotifyConnectView(auth_url)
            embed = discord.Embed(
                title=f"{Emojis.SPOTIFY} Connect Your Spotify Account",
                description=format_discord_emojis(
                    "Click the button below to authorize SyncInk Radio via official Spotify PKCE OAuth.\n\n"
                    f"{Emojis.S_ARROW} **Features Unlocked:**\n"
                    "• Stream your personal and private playlists\n"
                    "• Audia AI learns from your top played artists and genres\n"
                    "• Instant /spotify mytop track access\n\n"
                    "-# Tokens are securely encrypted with authenticated cryptography and never exposed."
                ),
                color=SPOTIFY_COLOR
            )
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            log.error(f"[Spotify Connect Error] {e}")
            embed = discord.Embed(description=format_discord_emojis(f"### {Emojis.REFUSED} Could not generate Spotify connection link: `{e}`"), color=0xED4245)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @spotify_group.command(name="disconnect", description="Unlink and disconnect your Spotify account from SyncInk Radio.")
    async def slash_spotify_disconnect(self, interaction: discord.Interaction):
        unlinked = await self.auth_mgr.unlink_user(interaction.user.id)
        if unlinked:
            embed = discord.Embed(
                description=format_discord_emojis(f"### {Emojis.CHECK_YES} Successfully unlinked your Spotify account. All stored tokens were revoked and deleted."),
                color=BRAND_COLOR
            )
        else:
            embed = discord.Embed(
                description=format_discord_emojis(f"### {Emojis.WARNING} No linked Spotify account was found for your Discord user."),
                color=0xFEE75C
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @spotify_group.command(name="status", description="Check whether your Spotify account is connected to SyncInk Radio.")
    async def slash_spotify_status(self, interaction: discord.Interaction):
        user_auth = await self.auth_mgr.get_user_auth(interaction.user.id)
        if user_auth and user_auth.spotify_user_id:
            member_name = interaction.user.display_name or interaction.user.name
            # If display name was default 'Spotify User' or starts with spotify_, heal to member's real Discord name
            if not user_auth.display_name or user_auth.display_name in ("Spotify User", "unknown") or user_auth.display_name.startswith("spotify_"):
                user_auth.display_name = member_name
                await db.execute("UPDATE spotify_users SET display_name = $1 WHERE discord_user_id = $2;", member_name, interaction.user.id)

            display_name = user_auth.display_name or member_name
            spotify_id = user_auth.spotify_user_id
            if spotify_id.startswith("spotify_") or spotify_id.startswith("user_") or spotify_id == str(interaction.user.id):
                spotify_id = f"@{interaction.user.name}"

            embed = discord.Embed(
                title=f"{Emojis.SPOTIFY} Spotify Connection Status",
                description=format_discord_emojis(
                    f"**Account Status:** Connected {Emojis.CHECK_YES}\n"
                    f"**Spotify Display Name:** `{display_name}`\n"
                    f"**Spotify User ID:** `{spotify_id}`\n"
                    f"**Token Storage:** Encrypted Vault {Emojis.LOCK}\n\n"
                    "-# You can disconnect anytime with `/spotify disconnect`."
                ),
                color=SPOTIFY_COLOR
            )
        else:
            embed = discord.Embed(
                title=f"{Emojis.SPOTIFY} Spotify Connection Status",
                description=format_discord_emojis(
                    f"**Account Status:** Not Connected {Emojis.REFUSED}\n\n"
                    "Connect your Spotify account using `/spotify connect` to stream your private playlists and sync your listening taste."
                ),
                color=BRAND_COLOR
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @spotify_group.command(name="mytop", description="Play or view your personal top tracks from Spotify.")
    @app_commands.describe(action="Enqueue tracks to queue or view list")
    async def slash_spotify_mytop(self, interaction: discord.Interaction, action: Optional[str] = "queue"):
        token = await self.auth_mgr.get_valid_user_token(interaction.user.id)
        if not token:
            embed = discord.Embed(
                description=format_discord_emojis(f"### {Emojis.WARNING} Please connect your Spotify account first using `/spotify connect`."),
                color=0xFEE75C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        # Fetch top tracks from Spotify Web API
        url = "https://api.spotify.com/v1/me/top/tracks?limit=10"
        headers = {"Authorization": f"Bearer {token}"}
        items = []

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("items", [])
                else:
                    log.debug(f"[Spotify] /v1/me/top/tracks returned HTTP {resp.status} for user {interaction.user.id}")

        source_label = "Spotify Top Tracks"
        # If Spotify returned empty or restricted, fallback to listener history on SyncInk Radio
        if not items:
            try:
                rows = await db.fetch("""
                    SELECT track_title, track_author, track_url, duration, thumbnail_url, COUNT(*) as play_count
                    FROM listening_history
                    WHERE discord_user_id = $1
                    GROUP BY track_title, track_author, track_url, duration, thumbnail_url
                    ORDER BY play_count DESC
                    LIMIT 10;
                """, interaction.user.id)
                if rows:
                    items = [
                        {
                            "name": r["track_title"],
                            "artists": [{"name": r["track_author"] or "Unknown Artist"}],
                            "duration_ms": (r["duration"] or 0) * 1000,
                            "external_urls": {"spotify": r["track_url"]},
                            "album": {"images": [{"url": r["thumbnail_url"]}] if r["thumbnail_url"] else []}
                        }
                        for r in rows
                    ]
                    source_label = "SyncInk Radio Listener History"
            except Exception:
                pass

        if not items:
            embed = discord.Embed(
                title=f"{Emojis.SPOTIFY} Your Top Tracks",
                description=format_discord_emojis(
                    f"### {Emojis.WARNING} No Top Tracks Available Yet\n\n"
                    "You haven't played enough tracks yet to build your top tracks list.\n\n"
                    f"• Play any song or playlist with `/play <song or link>`\n"
                    f"• Tune into 30,000+ stations with `/radio`\n\n"
                    "-# As you listen, your personalized top tracks and Audia AI taste profile will appear here automatically!"
                ),
                color=SPOTIFY_COLOR
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        music_cog = self.bot.get_cog("Music")
        if not music_cog:
            await interaction.followup.send("Music system is currently loading.", ephemeral=True)
            return

        # Build list of Tracks
        tracks_to_queue = []
        track_list_text = []
        for i, item in enumerate(items[:10], start=1):
            title = item.get("name", "Unknown Track")
            artists = ", ".join([a["name"] for a in item.get("artists", [])])
            duration_sec = int(item.get("duration_ms", 0)) // 1000
            spotify_url = item.get("external_urls", {}).get("spotify", "")
            images = item.get("album", {}).get("images", [])
            artwork = images[0].get("url") if images else None

            track_list_text.append(f"`{i:02d}.` **{title}** — {artists}")
            tracks_to_queue.append(
                Track(
                    title=title,
                    clean_title=clean_title(title),
                    author=artists,
                    duration=duration_sec,
                    url=spotify_url,
                    stream_url="",
                    thumbnail=artwork,
                    platform="spotify",
                    requested_by=interaction.user,
                    is_live=False
                )
            )

        if action and action.lower() == "view":
            embed = discord.Embed(
                title=f"{Emojis.SPOTIFY} Your Top Tracks",
                description="\n".join(track_list_text) + f"\n\n-# 🎵 Source: {source_label}",
                color=SPOTIFY_COLOR
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        vc = await music_cog.ensure_voice(interaction)
        if not vc:
            return

        queue = music_cog.service.get_queue(interaction.guild_id)
        queue.voice_client = vc
        queue.text_channel = interaction.channel

        await music_cog.enqueue_and_play(interaction, tracks_to_queue)

    @spotify_group.command(name="playlists", description="View and stream playlists from your linked Spotify library.")
    async def slash_spotify_playlists(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        music_cog = self.bot.get_cog("Music")
        if not music_cog:
            await interaction.followup.send("Music system is currently loading.", ephemeral=True)
            return

        items = await self.auth_mgr.get_user_playlists(interaction.user.id, limit=25)

        if not items:
            view = discord.ui.View(timeout=180)
            btn = discord.ui.Button(label="Add Public Playlist", emoji=EmojiPartials.QUEUE_ADD, style=discord.ButtonStyle.success)
            async def _open_modal(btn_interaction: discord.Interaction):
                await btn_interaction.response.send_modal(SpotifyAddPlaylistModal(music_cog))
            btn.callback = _open_modal
            view.add_item(btn)

            embed = discord.Embed(
                title=f"{Emojis.SPOTIFY} Your Spotify Playlists",
                description=format_discord_emojis(
                    f"### {Emojis.WARNING} No Playlists Found in Library\n\n"
                    "You don't have any saved playlists in your library yet.\n\n"
                    f"• Click **Add Public Playlist** below to save your public Spotify playlist link!\n"
                    f"• Or paste any playlist link directly: `/play <playlist_url>`\n"
                    f"• You can also add playlists anytime with `/spotify add <url>`\n\n"
                    "-# Saved playlists sync across Discord and the Web Dashboard automatically."
                ),
                color=SPOTIFY_COLOR
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            return

        view = SpotifyPlaylistsView(items, music_cog)
        embed = discord.Embed(
            title=f"{Emojis.SPOTIFY} Select a Playlist to Stream",
            description=f"Found **{len(items)}** playlists in your library. Select one below to begin streaming or click **Add Public Playlist** to add another:",
            color=SPOTIFY_COLOR
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @spotify_group.command(name="add", description="Add a public Spotify playlist or album to your SyncInk library.")
    @app_commands.describe(url="Public Spotify playlist or album URL (open.spotify.com/playlist/...)")
    async def slash_spotify_add(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer(ephemeral=True)
        from services.spotify.resolver import SpotifyResolver
        if not SpotifyResolver.is_spotify_url_or_uri(url):
            embed = discord.Embed(
                description=format_discord_emojis(f"### {Emojis.WARNING} Please provide a valid Spotify playlist or album link (`open.spotify.com/playlist/...`)."),
                color=0xFEE75C
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        pl = await self.auth_mgr.add_user_spotify_playlist(interaction.user.id, url)
        if not pl:
            embed = discord.Embed(
                description=format_discord_emojis(f"### {Emojis.REFUSED} Could not extract tracks from the provided link. Please ensure the playlist is public."),
                color=0xED4245
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(
            title=f"{Emojis.CHECK_YES} Added Spotify Playlist to Library",
            description=format_discord_emojis(
                f"**[{pl['name']}]({pl['url']})**\n\n"
                f"• Tracks: **{pl['tracks_total']}**\n"
                f"• Platform: Spotify\n\n"
                f"-# You can now stream it anytime with `/spotify playlists` or in the [Web Dashboard](https://syncink.site/dashboard/radio/#library)!"
            ),
            color=SPOTIFY_COLOR
        )
        if pl.get("image_url"):
            embed.set_thumbnail(url=pl["image_url"])
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ─────────────────────────────────────────────────────────────
    # Text Prefix Commands: ?spotify connect / ?spotify status / ?spotify disconnect
    # ─────────────────────────────────────────────────────────────

    @commands.group(name="spotify", invoke_without_command=True)
    async def cmd_spotify(self, ctx: commands.Context):
        embed = discord.Embed(
            title=f"{Emojis.SPOTIFY} SyncInk Spotify Integration",
            description=format_discord_emojis(
                f"**Available Commands:**\n"
                f"• `{ctx.prefix}spotify connect` — Link your Spotify account\n"
                f"• `{ctx.prefix}spotify status` — Check your connection status\n"
                f"• `{ctx.prefix}spotify disconnect` — Unlink and revoke tokens\n"
                f"• `/spotify mytop` — Play your top Spotify tracks\n"
                f"• `/spotify playlists` — Stream your Spotify playlists\n\n"
                f"-# You can also paste any Spotify track, album, or playlist URL directly into `/play`!"
            ),
            color=SPOTIFY_COLOR
        )
        await ctx.send(embed=embed)

    @cmd_spotify.command(name="connect")
    async def cmd_spotify_connect(self, ctx: commands.Context):
        if not self.client.is_configured:
            await ctx.send(embed=discord.Embed(description=f"{Emojis.WARNING} Spotify integration is temporarily unavailable. Please try again later.", color=0xFEE75C))
            return
        auth_url, state = await self.auth_mgr.generate_auth_url(ctx.author.id)
        view = SpotifyConnectView(auth_url)
        embed = discord.Embed(
            title=f"{Emojis.SPOTIFY} Connect Your Spotify Account",
            description=f"Click below to authorize SyncInk Radio via official Spotify PKCE OAuth.",
            color=SPOTIFY_COLOR
        )
        # Send via DM or in chat with delete hint
        try:
            await ctx.author.send(embed=embed, view=view)
            await ctx.send(f"{Emojis.CHECK_YES} Sent Spotify authorization link to your direct messages!")
        except discord.Forbidden:
            await ctx.send(embed=embed, view=view)

    @cmd_spotify.command(name="disconnect")
    async def cmd_spotify_disconnect(self, ctx: commands.Context):
        unlinked = await self.auth_mgr.unlink_user(ctx.author.id)
        if unlinked:
            await ctx.send(embed=discord.Embed(description=f"{Emojis.CHECK_YES} Unlinked your Spotify account successfully.", color=BRAND_COLOR))
        else:
            await ctx.send(embed=discord.Embed(description=f"{Emojis.WARNING} No linked Spotify account found.", color=0xFEE75C))

    @cmd_spotify.command(name="add")
    async def cmd_spotify_add(self, ctx: commands.Context, url: str):
        from services.spotify.resolver import SpotifyResolver
        if not SpotifyResolver.is_spotify_url_or_uri(url):
            await ctx.send(embed=discord.Embed(description=f"{Emojis.WARNING} Please provide a valid Spotify playlist link (`open.spotify.com/playlist/...`).", color=0xFEE75C))
            return
        pl = await self.auth_mgr.add_user_spotify_playlist(ctx.author.id, url)
        if pl:
            await ctx.send(embed=discord.Embed(description=f"{Emojis.CHECK_YES} Added **{pl['name']}** ({pl['tracks_total']} tracks) to your Spotify library!", color=SPOTIFY_COLOR))
        else:
            await ctx.send(embed=discord.Embed(description=f"{Emojis.REFUSED} Could not load public Spotify playlist.", color=0xED4245))

    @cmd_spotify.command(name="status")
    async def cmd_spotify_status(self, ctx: commands.Context):
        user_auth = await self.auth_mgr.get_user_auth(ctx.author.id)
        if user_auth and user_auth.spotify_user_id:
            await ctx.send(embed=discord.Embed(description=f"{Emojis.CHECK_YES} Connected to Spotify as `{user_auth.display_name}`.", color=SPOTIFY_COLOR))
        else:
            await ctx.send(embed=discord.Embed(description=f"{Emojis.REFUSED} Not connected to Spotify. Type `{ctx.prefix}spotify connect` to link.", color=BRAND_COLOR))

async def setup(bot: commands.Bot):
    await bot.add_cog(Spotify(bot))
