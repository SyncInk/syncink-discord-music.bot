import asyncio
import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Optional

from services.updater_service import UpdaterService
from utils.emojis import Emojis, format_discord_emojis
from utils.logger import log

BRAND_COLOR = 0x7b2cbf
BRAND_LOGO_URL = "https://files.catbox.moe/74l9su.png"


def is_admin_or_owner(user: discord.Member, guild: Optional[discord.Guild] = None) -> bool:
    """Checks whether the user is a server administrator or bot owner."""
    if guild and user.id == guild.owner_id:
        return True
    if getattr(user.guild_permissions, "administrator", False):
        return True
    owner_env = os.getenv("BOT_OWNER_ID") or os.getenv("OWNER_ID")
    if owner_env and str(user.id) == owner_env.strip():
        return True
    return False


class Updater(commands.Cog):
    """
    Automated GitHub updater & self-restarting service for SyncInk Radio.
    Monitors GitHub for new commits 24/7, pulls updates silently, and restarts seamlessly.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.updater = UpdaterService.get_instance()
        self.is_updating = False

        # Read configuration from environment
        enabled_raw = os.getenv("AUTO_UPDATE_ENABLED", "true").lower().strip()
        self.auto_update_enabled = enabled_raw in ("true", "1", "yes", "on")

        interval_raw = os.getenv("AUTO_UPDATE_INTERVAL", "60").strip()
        try:
            self.interval_seconds = max(15, int(interval_raw))
        except ValueError:
            self.interval_seconds = 60

        if self.auto_update_enabled and self.updater.is_git_repo():
            self.auto_update_task.change_interval(seconds=self.interval_seconds)
            self.auto_update_task.start()
            log.info(f"[AutoUpdater] Service initialized. Checking GitHub every {self.interval_seconds}s.")
        else:
            log.info("[AutoUpdater] Standalone mode (manual /update & /restart available).")

    def cog_unload(self):
        if self.auto_update_task.is_running():
            self.auto_update_task.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        """Notifies channel upon reboot if bot recently restarted from an update."""
        notice = self.updater.consume_restart_notice()
        if not notice:
            return

        channel_id = notice.get("channel_id")
        commit_hash = notice.get("commit", "Latest")
        summary = notice.get("summary", "Codebase updated.")

        channel = self.bot.get_channel(channel_id) if channel_id else None
        if not channel:
            # Fallback: find first available text channel
            for guild in self.bot.guilds:
                channel = guild.system_channel
                if channel:
                    break

        if channel:
            try:
                embed = discord.Embed(
                    description=format_discord_emojis(
                        f"### {Emojis.CHECK_YES} SyncInk Radio is back online!\n"
                        f"Successfully updated to commit `{commit_hash}`:\n"
                        f"> *{summary}*\n\n"
                        f"{Emojis.S_ARROW} *All audio engines and 24/7 radio services are operational.*"
                    ),
                    color=BRAND_COLOR
                )
                embed.set_footer(text="SyncInk Automated Continuous Deployment", icon_url=BRAND_LOGO_URL)
                await channel.send(embed=embed)
            except Exception as e:
                log.warning(f"[AutoUpdater] Could not send startup update notification: {e}")

    @tasks.loop(seconds=60)
    async def auto_update_task(self):
        """Background loop to check GitHub for new commits and auto-restart."""
        if self.is_updating or not self.auto_update_enabled:
            return

        try:
            update_info = await asyncio.to_thread(self.updater.check_for_updates)
            if not update_info:
                return

            self.is_updating = True
            remote_hash = update_info["remote_hash"]
            summary = update_info["summary"]
            log.info(f"[AutoUpdater] New commit detected on GitHub: {remote_hash} - {summary}")

            # Pull updates
            success, output = await asyncio.to_thread(self.updater.pull_updates)
            if not success:
                log.error(f"[AutoUpdater] Git pull failed: {output}")
                self.is_updating = False
                return

            log.info(f"[AutoUpdater] Successfully pulled updates! Output: {output}")

            # Find active channel to announce restart
            notice_channel_id = None
            active_channels = []
            for vc in self.bot.voice_clients:
                if vc.channel:
                    # Look up music text channel for this guild
                    try:
                        from services.music_service import MusicService
                        q = MusicService.get_instance().get_queue(vc.guild.id)
                        if q.text_channel:
                            active_channels.append(q.text_channel)
                    except Exception:
                        pass

            if active_channels:
                notice_channel_id = active_channels[0].id
                embed_updating = discord.Embed(
                    description=format_discord_emojis(
                        f"### {Emojis.WARNING} Auto-Update: Applied new commit `{remote_hash}`!\n"
                        f"> *{summary}*\n\n"
                        f"{Emojis.S_ARROW} *Restarting bot now... Back online in ~3 seconds.*"
                    ),
                    color=BRAND_COLOR
                )
                for ch in active_channels:
                    try:
                        await ch.send(embed=embed_updating)
                    except Exception:
                        pass

            # Persist notice for post-restart confirmation
            self.updater.save_restart_notice({
                "channel_id": notice_channel_id,
                "commit": remote_hash,
                "summary": summary
            })

            # Execute restart
            await self.updater.restart_bot(self.bot, delay=1.5)
        except Exception as e:
            log.warning(f"[AutoUpdater] Loop encountered exception: {e}")
            self.is_updating = False

    @auto_update_task.before_loop
    async def before_auto_update(self):
        await self.bot.wait_until_ready()

    # ==========================================
    # SLASH COMMANDS
    # ==========================================

    @app_commands.command(name="update", description="Check GitHub for latest commits, pull updates, and restart bot.")
    async def slash_update(self, interaction: discord.Interaction):
        if not is_admin_or_owner(interaction.user, interaction.guild):
            embed = discord.Embed(
                description=f"### {Emojis.REFUSED} Only server administrators or bot owners can trigger updates.",
                color=0xED4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        if self.is_updating:
            embed = discord.Embed(description=f"### {Emojis.WARNING} An update is already in progress.", color=0xFEE75C)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer(ephemeral=False)

        update_info = await asyncio.to_thread(self.updater.check_for_updates)
        if not update_info:
            h, s, d = self.updater.get_current_commit()
            embed = discord.Embed(
                description=format_discord_emojis(
                    f"### {Emojis.CHECK_YES} SyncInk Radio is already on the latest commit!\n\n"
                    f"{Emojis.S_ARROW} **Commit:** `{h}`\n"
                    f"{Emojis.S_ARROW} **Message:** *{s}*\n"
                    f"{Emojis.S_ARROW} **Date:** {d}"
                ),
                color=BRAND_COLOR
            )
            embed.set_footer(text="GitHub Repository is Up to Date", icon_url=BRAND_LOGO_URL)
            await interaction.followup.send(embed=embed)
            return

        self.is_updating = True
        remote_hash = update_info["remote_hash"]
        summary = update_info["summary"]

        success, output = await asyncio.to_thread(self.updater.pull_updates)
        if not success:
            self.is_updating = False
            embed = discord.Embed(
                description=f"### {Emojis.REFUSED} Git pull failed:\n```{output}```",
                color=0xED4245
            )
            await interaction.followup.send(embed=embed)
            return

        embed = discord.Embed(
            description=format_discord_emojis(
                f"### {Emojis.CHECK_YES} Pulled commit `{remote_hash}` from GitHub!\n"
                f"> *{summary}*\n\n"
                f"{Emojis.S_ARROW} *Restarting bot now... Back online in ~3 seconds.*"
            ),
            color=BRAND_COLOR
        )
        await interaction.followup.send(embed=embed)

        self.updater.save_restart_notice({
            "channel_id": interaction.channel_id,
            "commit": remote_hash,
            "summary": summary
        })

        await self.updater.restart_bot(self.bot, delay=1.5)

    @app_commands.command(name="restart", description="Gracefully reboot the SyncInk Radio process.")
    async def slash_restart(self, interaction: discord.Interaction):
        if not is_admin_or_owner(interaction.user, interaction.guild):
            embed = discord.Embed(
                description=f"### {Emojis.REFUSED} Only server administrators or bot owners can restart the bot.",
                color=0xED4245
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        h, s, _ = self.updater.get_current_commit()
        embed = discord.Embed(
            description=format_discord_emojis(
                f"### {Emojis.SYNCBOT} Restarting SyncInk Radio...\n"
                f"{Emojis.S_ARROW} *Saving state and unbinding voice protocols. Back online in ~3 seconds.*"
            ),
            color=BRAND_COLOR
        )
        await interaction.response.send_message(embed=embed)

        self.updater.save_restart_notice({
            "channel_id": interaction.channel_id,
            "commit": h,
            "summary": "Manual process restart"
        })

        await self.updater.restart_bot(self.bot, delay=1.5)

    @app_commands.command(name="gitstatus", description="View current Git commit and deployment version.")
    async def slash_gitstatus(self, interaction: discord.Interaction):
        h, s, d = self.updater.get_current_commit()
        embed = discord.Embed(
            title=f"{Emojis.SYNCINK_MUSIC} SyncInk Radio Version & Git Status",
            description=format_discord_emojis(
                f"{Emojis.S_ARROW} **Commit:** `{h}`\n"
                f"{Emojis.S_ARROW} **Message:** *{s}*\n"
                f"{Emojis.S_ARROW} **Last Commit:** {d}\n"
                f"{Emojis.S_ARROW} **Auto-Updater:** `{'ENABLED (' + str(self.interval_seconds) + 's)' if self.auto_update_enabled else 'DISABLED'}`"
            ),
            color=BRAND_COLOR
        )
        embed.set_footer(text="SyncInk Continuous Deployment Engine", icon_url=BRAND_LOGO_URL)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==========================================
    # PREFIX COMMANDS (?)
    # ==========================================

    @commands.command(name="update", description="Check GitHub for latest commits, pull updates, and restart bot.")
    async def cmd_update(self, ctx: commands.Context):
        if not is_admin_or_owner(ctx.author, ctx.guild):
            embed = discord.Embed(
                description=f"### {Emojis.REFUSED} Only server administrators or bot owners can trigger updates.",
                color=0xED4245
            )
            await ctx.send(embed=embed, delete_after=5)
            return

        if self.is_updating:
            embed = discord.Embed(description=f"### {Emojis.WARNING} An update is already in progress.", color=0xFEE75C)
            await ctx.send(embed=embed, delete_after=5)
            return

        check_msg = await ctx.send(embed=discord.Embed(description=f"### {Emojis.WARNING} Checking GitHub for updates...", color=BRAND_COLOR))

        update_info = await asyncio.to_thread(self.updater.check_for_updates)
        if not update_info:
            h, s, d = self.updater.get_current_commit()
            embed = discord.Embed(
                description=format_discord_emojis(
                    f"### {Emojis.CHECK_YES} SyncInk Radio is already on the latest commit!\n\n"
                    f"{Emojis.S_ARROW} **Commit:** `{h}`\n"
                    f"{Emojis.S_ARROW} **Message:** *{s}*\n"
                    f"{Emojis.S_ARROW} **Date:** {d}"
                ),
                color=BRAND_COLOR
            )
            await check_msg.edit(embed=embed)
            return

        self.is_updating = True
        remote_hash = update_info["remote_hash"]
        summary = update_info["summary"]

        success, output = await asyncio.to_thread(self.updater.pull_updates)
        if not success:
            self.is_updating = False
            embed = discord.Embed(description=f"### {Emojis.REFUSED} Git pull failed:\n```{output}```", color=0xED4245)
            await check_msg.edit(embed=embed)
            return

        embed = discord.Embed(
            description=format_discord_emojis(
                f"### {Emojis.CHECK_YES} Pulled commit `{remote_hash}` from GitHub!\n"
                f"> *{summary}*\n\n"
                f"{Emojis.S_ARROW} *Restarting bot now... Back online in ~3 seconds.*"
            ),
            color=BRAND_COLOR
        )
        await check_msg.edit(embed=embed)

        self.updater.save_restart_notice({
            "channel_id": ctx.channel.id,
            "commit": remote_hash,
            "summary": summary
        })

        await self.updater.restart_bot(self.bot, delay=1.5)

    @commands.command(name="restart", description="Gracefully reboot the SyncInk Radio process.")
    async def cmd_restart(self, ctx: commands.Context):
        if not is_admin_or_owner(ctx.author, ctx.guild):
            embed = discord.Embed(
                description=f"### {Emojis.REFUSED} Only server administrators or bot owners can restart the bot.",
                color=0xED4245
            )
            await ctx.send(embed=embed, delete_after=5)
            return

        h, s, _ = self.updater.get_current_commit()
        embed = discord.Embed(
            description=format_discord_emojis(
                f"### {Emojis.SYNCBOT} Restarting SyncInk Radio...\n"
                f"{Emojis.S_ARROW} *Saving state and unbinding voice protocols. Back online in ~3 seconds.*"
            ),
            color=BRAND_COLOR
        )
        await ctx.send(embed=embed)

        self.updater.save_restart_notice({
            "channel_id": ctx.channel.id,
            "commit": h,
            "summary": "Manual process restart"
        })

        await self.updater.restart_bot(self.bot, delay=1.5)

    @commands.command(name="gitstatus", description="View current Git commit and deployment version.")
    async def cmd_gitstatus(self, ctx: commands.Context):
        h, s, d = self.updater.get_current_commit()
        embed = discord.Embed(
            title=f"{Emojis.SYNCINK_MUSIC} SyncInk Radio Version & Git Status",
            description=format_discord_emojis(
                f"{Emojis.S_ARROW} **Commit:** `{h}`\n"
                f"{Emojis.S_ARROW} **Message:** *{s}*\n"
                f"{Emojis.S_ARROW} **Last Commit:** {d}\n"
                f"{Emojis.S_ARROW} **Auto-Updater:** `{'ENABLED (' + str(self.interval_seconds) + 's)' if self.auto_update_enabled else 'DISABLED'}`"
            ),
            color=BRAND_COLOR
        )
        embed.set_footer(text="SyncInk Continuous Deployment Engine", icon_url=BRAND_LOGO_URL)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Updater(bot))
