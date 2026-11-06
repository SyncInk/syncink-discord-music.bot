import discord
from discord.ext import commands
import asyncio
import os
import sys
import traceback
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from utils.logger import log
from utils.exceptions import ConfigurationError, UserFacingError
from utils.ui import ErrorEmbed
from utils.validator import validate_environment
from utils.i18n import i18n
from utils.tasks import task_manager
from utils.davey_shim import ensure_davey_loaded
from services.music_service import ensure_opus_loaded
from database import db

# Initialize low-level voice protocols
ensure_davey_loaded()
ensure_opus_loaded()

class SyncInkRadioBot(commands.Bot):
    def __init__(self, enable_presences: bool = True):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.voice_states = True
        if enable_presences:
            intents.presences = True
        
        super().__init__(
            command_prefix="?",
            intents=intents,
            help_command=None,
            case_insensitive=True
        )
        
    async def setup_hook(self):
        """Initializes dependencies, DB, background tasks, and loads cogs."""
        log.info("Setting up SyncInk Radio Engine...")
        
        # Load localizations
        i18n.load_locales()
        
        # Connect to Database (PostgreSQL or local SQLite)
        try:
            await db.connect()
        except Exception as e:
            log.critical(f"Failed to connect to database: {e}")
            sys.exit(1)

        # Load Cogs dynamically from cogs/
        cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
        if os.path.exists(cogs_dir):
            for filename in os.listdir(cogs_dir):
                if filename.endswith(".py") and not filename.startswith("__"):
                    cog_name = f"cogs.{filename[:-3]}"
                    try:
                        await self.load_extension(cog_name)
                        log.info(f"Loaded extension: {cog_name}")
                    except Exception as e:
                        log.error(f"Failed to load extension {cog_name}: {e}")
                        traceback.print_exc()

        # Application Slash Command Tree Synchronization
        try:
            target_guild_raw = os.getenv("TARGET_GUILD_ID") or os.getenv("DISCORD_GUILD_ID")
            if target_guild_raw and target_guild_raw.strip():
                target_guild_id = int(target_guild_raw.strip())
                target_guild = discord.Object(id=target_guild_id)
                self.tree.copy_global_to(guild=target_guild)
                synced_guild = await self.tree.sync(guild=target_guild)
                log.info(f"Instantly synced {len(synced_guild)} slash commands to target guild ({target_guild_id}).")
            
            synced_global = await self.tree.sync()
            log.info(f"Globally synced {len(synced_global)} slash commands.")
        except Exception as e:
            log.warning(f"Failed to sync slash commands: {e}")

    async def on_message(self, message: discord.Message):
        """Global message processor; ignores DMs and bots."""
        if message.guild is None or message.author.bot:
            return
        await self.process_commands(message)

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        log.info("SyncInk Radio Platform is online and ready.")
        try:
            activity = discord.Activity(
                type=discord.ActivityType.listening,
                name="/play | SyncInk Radio & AI DJ"
            )
            await self.change_presence(status=discord.Status.online, activity=activity)
        except Exception as e:
            log.debug(f"Could not update presence: {e}")

    async def close(self):
        """Graceful shutdown handler."""
        log.info("Shutting down bot gracefully...")
        task_manager.cancel_all()
        await db.close()
        await super().close()

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Global error handler for prefix commands."""
        if ctx.guild is None:
            return

        if isinstance(error, commands.CommandNotFound):
            return

        if isinstance(error, (commands.MissingPermissions, commands.NotOwner)):
            await ctx.send(embed=ErrorEmbed("You do not have permission to execute this command."), delete_after=5)
            return

        if isinstance(error, commands.CheckFailure):
            return
            
        if hasattr(error, 'original') and isinstance(error.original, UserFacingError):
            await ctx.send(embed=ErrorEmbed(error.original.message))
            return

        log.error(f"Exception in command {ctx.command}: {error}")
        traceback.print_exception(type(error), error, error.__traceback__)
        try:
            await ctx.send(embed=ErrorEmbed(i18n.get("error_generic")))
        except discord.HTTPException:
            pass

def main():
    validate_environment()
    token = os.getenv("DISCORD_TOKEN")
    
    def run_bot(enable_presences: bool):
        bot = SyncInkRadioBot(enable_presences=enable_presences)
        
        @bot.tree.error
        async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
            if hasattr(error, 'original') and isinstance(error.original, UserFacingError):
                if not interaction.response.is_done():
                    await interaction.response.send_message(embed=ErrorEmbed(error.original.message), ephemeral=True)
                return
                
            orig = getattr(error, 'original', error)
            if isinstance(orig, discord.errors.NotFound) and orig.code == 10062:
                return

            log.error(f"Exception in app command {interaction.command}: {error}")
            traceback.print_exception(type(error), error, error.__traceback__)

            cog = interaction.command.binding if interaction.command else None
            if cog and hasattr(cog, "cog_app_command_error"):
                return

            try:
                err_msg = (
                    "### <a:refused:1547035200926654624> Something went wrong while running the command, "
                    "please try again or contact server administrator on "
                    "https://discord.com/channels/1520457643842342912/1520460764937322566"
                )
                err_embed = discord.Embed(description=err_msg, color=0xED4245)
                if interaction.response.is_done():
                    await interaction.followup.send(embed=err_embed, ephemeral=True)
                else:
                    await interaction.response.send_message(embed=err_embed, ephemeral=True)
            except discord.HTTPException:
                pass

        bot.run(token, log_handler=None)

    try:
        run_bot(enable_presences=True)
    except discord.errors.PrivilegedIntentsRequired:
        log.warning("Privileged Presence Intent is not enabled in Discord Developer Portal. Running with standard intents...")
        run_bot(enable_presences=False)

if __name__ == "__main__":
    main()
