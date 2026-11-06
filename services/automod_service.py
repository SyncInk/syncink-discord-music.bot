import discord
from discord.ext import commands
from datetime import datetime, timedelta
from collections import defaultdict, deque
from typing import Dict, Deque
from utils.logger import log
from utils.ui import SyncInkEmbed, ErrorEmbed, WARNING_COLOR, ERROR_COLOR
from utils.emojis import Emojis

class AutomodService:
    """Security ladder and rate limiting service for moderation and command usage."""
    _unauthorized_attempts: Dict[int, Deque[datetime]] = defaultdict(lambda: deque(maxlen=5))
    _command_timestamps: Dict[int, Deque[datetime]] = defaultdict(lambda: deque(maxlen=20))

    @classmethod
    async def check_command_rate_limit(cls, ctx: commands.Context) -> bool:
        """Rate limit protection against command flooding (max 7 commands per 5 seconds)."""
        if not ctx.guild or not ctx.author:
            return True
        if ctx.author.id == ctx.guild.owner_id or getattr(ctx.author.guild_permissions, "administrator", False):
            return True

        now = datetime.utcnow()
        queue = cls._command_timestamps[ctx.author.id]
        while queue and (now - queue[0]).total_seconds() > 5.0:
            queue.popleft()

        if len(queue) >= 7:
            embed = ErrorEmbed(
                description="You are issuing commands too quickly. Please slow down.",
                resolution="Wait a few seconds before trying again."
            )
            try:
                await ctx.send(embed=embed, delete_after=5)
            except Exception:
                pass
            return False

        queue.append(now)
        return True

    @classmethod
    async def handle_unauthorized_command(cls, ctx: commands.Context, command_name: str):
        """Progressive enforcement ladder for unauthorized attempts to run staff commands."""
        try:
            if not ctx.guild or not ctx.author:
                return

            try:
                await ctx.message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

            now = datetime.utcnow()
            user_id = ctx.author.id
            attempts = cls._unauthorized_attempts[user_id]
            while attempts and (now - attempts[0]).total_seconds() > 60:
                attempts.popleft()

            attempts.append(now)
            count = len(attempts)

            if count == 1:
                embed = SyncInkEmbed(
                    title=f"{Emojis.REFUSED} Access Denied",
                    description=f"You do not possess the required staff permissions to execute `?{command_name}`.",
                    color=ERROR_COLOR
                )
                try:
                    msg = await ctx.send(content=ctx.author.mention, embed=embed)
                    await msg.delete(delay=5)
                except Exception:
                    pass
            elif count == 2:
                embed = SyncInkEmbed(
                    title=f"{Emojis.WARNING} Security Warning",
                    description=(
                        f"Repeated unauthorized execution of restricted staff commands (`?{command_name}`) has been detected.\n\n"
                        f"⚠️ **Notice:** Further unauthorized attempts will be logged."
                    ),
                    color=WARNING_COLOR
                )
                try:
                    msg = await ctx.send(content=ctx.author.mention, embed=embed)
                    await msg.delete(delay=8)
                except Exception:
                    pass
            else:
                embed = SyncInkEmbed(
                    title=f"{Emojis.ALERT} Staff Notification",
                    description=f"Unauthorized access attempts by {ctx.author.mention} have been logged for staff review.",
                    color=ERROR_COLOR
                )
                try:
                    msg = await ctx.send(content=ctx.author.mention, embed=embed)
                    await msg.delete(delay=10)
                except Exception:
                    pass
                log.warning(f"[Security] Multiple unauthorized command attempts ({count}) by {ctx.author} ({ctx.author.id}) in guild {ctx.guild.id}")
        except Exception as e:
            log.error(f"Error handling unauthorized command: {e}")
