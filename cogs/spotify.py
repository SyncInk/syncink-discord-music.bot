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
                    SELECT track_title, track_artist, track_url, duration, thumbnail_url, platform
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
                        title=r["track_title"],
                        clean_title=clean_title(r["track_title"]),
                        author=r["track_artist"] or "Unknown Artist",
                        duration=int(r["duration"] or 0),
                        url=r["track_url"],
                        stream_url="",
                        thumbnail=r["thumbnail_url"],
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
        playlist_url = playlist_data.get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{playlist_id}")

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

class SpotifyPlaylistsView(discord.ui.View):
    def __init__(self, playlists: List[Dict[str, Any]], music_cog: Any):
        super().__init__(timeout=180)
        self.add_item(SpotifyPlaylistsSelect(playlists, music_cog))


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
                    f"### {Emojis.WARNING} Spotify Developer API Not Configured\n"
                    "The bot administrator has not configured `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in `.env` yet."
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
            if spotify_id.startswith("spotify_") or spotify_id.startswith("user_"):
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

        await interaction.response.defer()
        # Fetch top tracks from Spotify Web API
        url = "https://api.spotify.com/v1/me/top/tracks?limit=10"
        headers = {"Authorization": f"Bearer {token}"}
        items = []
        is_dev_mode = False

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("items", [])
                else:
                    if resp.status == 403:
                        is_dev_mode = True
                        log.debug(f"[Spotify] /v1/me/top/tracks returned 403 for {interaction.user.id} (Spotify Dev Mode user allowlist required).")
                    else:
                        log.warning(f"[Spotify] /v1/me/top/tracks returned HTTP {resp.status} for user {interaction.user.id}")

        source_label = "Spotify Live Top Tracks"
        # If Spotify returned empty or blocked by Dev Mode (HTTP 403), fallback to listener history on SyncInk Radio
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
            if is_dev_mode:
                embed = discord.Embed(
                    title=f"{Emojis.SPOTIFY} Spotify Developer Mode Setup Required",
                    description=format_discord_emojis(
                        f"### {Emojis.WARNING} Top Tracks Restricted (HTTP 403)\n\n"
                        "Your Spotify Developer App is currently in **Development Mode**.\n"
                        "In Development Mode, Spotify blocks personal top tracks until your email is added:\n\n"
                        "1️⃣ Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)\n"
                        "2️⃣ Open your app ➔ **Settings** ➔ **User Management** (or **Users and Access**)\n"
                        "3️⃣ Add your Spotify account email to the allowlist\n\n"
                        "-# *Tip: You can play any track or playlist directly using `/play <song_name or url>`!*"
                    ),
                    color=0xFEE75C
                )
            else:
                embed = discord.Embed(
                    description=format_discord_emojis(f"### {Emojis.WARNING} No top tracks found on your Spotify profile or listening history."),
                    color=0xFEE75C
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
            footer_note = f"\n\n-# 🎵 Source: {source_label}"
            if is_dev_mode:
                footer_note += "\n-# 💡 Tip: To sync live Spotify account data, add your email in Spotify Developer Dashboard > User Management."
            embed = discord.Embed(
                title=f"{Emojis.SPOTIFY} Your Top Tracks",
                description="\n".join(track_list_text) + footer_note,
                color=SPOTIFY_COLOR
            )
            await interaction.followup.send(embed=embed)
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
        token = await self.auth_mgr.get_valid_user_token(interaction.user.id)
        if not token:
            embed = discord.Embed(
                description=format_discord_emojis(f"### {Emojis.WARNING} Please connect your Spotify account first using `/spotify connect`."),
                color=0xFEE75C
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        url = "https://api.spotify.com/v1/me/playlists?limit=25"
        headers = {"Authorization": f"Bearer {token}"}
        items = []
        is_dev_mode = False

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("items", [])
                else:
                    if resp.status == 403:
                        is_dev_mode = True
                        log.debug(f"[Spotify] /v1/me/playlists returned 403 for {interaction.user.id} (Spotify Dev Mode user allowlist required).")
                    else:
                        log.warning(f"[Spotify] /v1/me/playlists returned HTTP {resp.status} for user {interaction.user.id}")

        # If Spotify returned empty or was blocked by Dev Mode (HTTP 403), fallback to SyncInk library playlists
        if not items:
            try:
                db_playlists = await db.fetch("""
                    SELECT p.id, p.name, p.description,
                           (SELECT COUNT(*) FROM user_playlist_tracks pt WHERE pt.playlist_id = p.id) as total_tracks
                    FROM user_playlists p
                    WHERE p.discord_user_id = $1
                    ORDER BY p.updated_at DESC;
                """, interaction.user.id)
                if db_playlists:
                    items = [
                        {
                            "id": f"syncink_{p['id']}",
                            "name": p["name"],
                            "description": p.get("description") or "SyncInk Radio Library Playlist",
                            "tracks": {"total": int(p["total_tracks"] or 0)},
                            "images": [{"url": "https://files.catbox.moe/74l9su.png"}],
                            "external_urls": {"spotify": "https://syncink.site/dashboard/radio/#library"},
                            "owner": {"display_name": "SyncInk Library"}
                        }
                        for p in db_playlists
                    ]
            except Exception:
                pass

        if not items:
            if is_dev_mode:
                embed = discord.Embed(
                    title=f"{Emojis.SPOTIFY} SyncInk Spotify Playlists",
                    description=format_discord_emojis(
                        f"### {Emojis.WARNING} Private Playlists Restricted (HTTP 403)\n\n"
                        "Your Spotify Developer App is currently in **Development Mode**.\n"
                        "To let the bot automatically list your personal Spotify playlists:\n\n"
                        "1️⃣ Visit [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)\n"
                        "2️⃣ Open your app ➔ **Settings** ➔ **User Management**\n"
                        "3️⃣ Add your Spotify email to the allowlist\n\n"
                        "• **Instant Alternative:** Play any playlist directly with `/play <spotify_playlist_url>`\n"
                        "• **Custom Library:** Create & import playlists anytime in the [Web Dashboard](https://syncink.site/dashboard/radio/#library)"
                    ),
                    color=0xFEE75C
                )
            else:
                embed = discord.Embed(
                    description=format_discord_emojis(f"### {Emojis.WARNING} No playlists found in your library."),
                    color=0xFEE75C
                )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        music_cog = self.bot.get_cog("Music")
        view = SpotifyPlaylistsView(items, music_cog)
        embed = discord.Embed(
            title=f"{Emojis.SPOTIFY} Select a Playlist to Stream",
            description=f"Found **{len(items)}** playlists in your library. Select one below to begin streaming:",
            color=SPOTIFY_COLOR
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

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
            await ctx.send(embed=discord.Embed(description=f"{Emojis.WARNING} Spotify API credentials are not configured in `.env`.", color=0xFEE75C))
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

    @cmd_spotify.command(name="status")
    async def cmd_spotify_status(self, ctx: commands.Context):
        user_auth = await self.auth_mgr.get_user_auth(ctx.author.id)
        if user_auth and user_auth.spotify_user_id:
            await ctx.send(embed=discord.Embed(description=f"{Emojis.CHECK_YES} Connected to Spotify as `{user_auth.display_name}`.", color=SPOTIFY_COLOR))
        else:
            await ctx.send(embed=discord.Embed(description=f"{Emojis.REFUSED} Not connected to Spotify. Type `{ctx.prefix}spotify connect` to link.", color=BRAND_COLOR))

async def setup(bot: commands.Bot):
    await bot.add_cog(Spotify(bot))
