import discord
import time
from typing import Optional, Union, Any
from utils.emojis import Emojis, EmojiPartials

# SyncInk Brand Colors
BRAND_PRIMARY = 0x2b2d31  # Modern dark color
BRAND_ACCENT = 0x7b2cbf   # SyncInk Cyber Violet (Music & Radio brand color)
SUCCESS_COLOR = 0x57F287  # Green
ERROR_COLOR = 0xED4245    # Red
WARNING_COLOR = 0xFEE75C  # Yellow
BRAND_LOGO_URL = "https://files.catbox.moe/74l9su.png"

def get_latency_badge(latency_ms: float) -> tuple[str, str]:
    """Returns (emoji, quality_label) based on gateway websocket latency."""
    if latency_ms <= 0:
        return Emojis.CONNECTION_NONE, "Offline"
    elif latency_ms <= 150:
        return Emojis.CONNECTION_GOOD, "Optimal"
    elif latency_ms <= 350:
        return Emojis.CONNECTION_MODERATE, "Moderate"
    else:
        return Emojis.CONNECTION_LOW, "High Latency"

async def send_clean_v2_message(destination: Any, layout_view: discord.ui.LayoutView, fallback_embed: Optional[discord.Embed] = None, reply: bool = False):
    """
    Sends a message using Discord Components V2 (flags: 32768, Container, Separator).
    If Components V2 fails in a specific context or client, gracefully falls back to fallback_embed.
    """
    if reply and hasattr(destination, 'reply'):
        try:
            return await destination.reply(view=layout_view, mention_author=False)
        except Exception:
            pass
        if fallback_embed is not None:
            try:
                return await destination.reply(embed=fallback_embed, mention_author=False)
            except Exception:
                pass

    try:
        return await destination.send(view=layout_view)
    except Exception as e:
        if fallback_embed is not None:
            return await destination.send(embed=fallback_embed)
        raise e


class SyncInkEmbed(discord.Embed):
    """Premium Base Embed class for the SyncInk Radio & Music Platform."""
    
    def __init__(self, color: int = BRAND_ACCENT, **kwargs):
        super().__init__(color=color, **kwargs)
        self.timestamp = discord.utils.utcnow()
        self.set_footer(text="SyncInk Platform", icon_url=BRAND_LOGO_URL)

class SuccessEmbed(SyncInkEmbed):
    def __init__(self, description: str, **kwargs):
        super().__init__(color=SUCCESS_COLOR, description=description, **kwargs)
        self.title = f"{Emojis.APPROVED} Action Successful"

class ErrorEmbed(SyncInkEmbed):
    def __init__(self, description: str, resolution: str = "Please contact a server administrator if the issue persists.", **kwargs):
        super().__init__(color=ERROR_COLOR, description=description, **kwargs)
        self.title = f"{Emojis.REFUSED} Action Required"
        self.add_field(name="How to fix this?", value=f"> {resolution}", inline=False)

class BaseConfirmView(discord.ui.View):
    """A standard confirmation view with Yes/No buttons."""
    def __init__(self, timeout: float = 60.0):
        super().__init__(timeout=timeout)
        self.value: Optional[bool] = None

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.green, custom_id="confirm_btn", emoji=EmojiPartials.CHECK_YES)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, custom_id="cancel_btn", emoji=EmojiPartials.REFUSED)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()

class LoadingEmbed(SyncInkEmbed):
    def __init__(self, description: str = "Processing request...", **kwargs):
        super().__init__(color=BRAND_ACCENT, description=description, **kwargs)
        self.title = f"{Emojis.ALERT} Please Wait"

class EmptyStateEmbed(SyncInkEmbed):
    def __init__(self, title: str, description: str, **kwargs):
        super().__init__(color=BRAND_PRIMARY, description=description, **kwargs)
        self.title = f"{Emojis.REFUSED} {title}"

class InfoCard(SyncInkEmbed):
    def __init__(self, title: str, description: str, **kwargs):
        super().__init__(color=BRAND_ACCENT, title=title, description=description, **kwargs)

class PaginationView(discord.ui.View):
    """A generic pagination view for embeds."""
    def __init__(self, embeds: list[discord.Embed]):
        super().__init__(timeout=120.0)
        self.embeds = embeds
        self.current_page = 0
        
    async def update_buttons(self, interaction: discord.Interaction):
        for child in self.children:
            if child.custom_id == "prev_btn":
                child.disabled = self.current_page == 0
            elif child.custom_id == "next_btn":
                child.disabled = self.current_page == len(self.embeds) - 1
                
        await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.secondary, custom_id="prev_btn", disabled=True)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page -= 1
        await self.update_buttons(interaction)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.secondary, custom_id="next_btn")
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_page += 1
        await self.update_buttons(interaction)

_recent_mute_dms = {}

async def send_mute_dm(member: discord.Member, reason: str = "No reason provided", server_name: str = None):
    """Sends a standardized mute notification DM to a member."""
    now = time.time()
    last_sent = _recent_mute_dms.get(member.id, 0)
    if now - last_sent < 5:
        return

    _recent_mute_dms[member.id] = now
    s_name = server_name or getattr(member.guild, 'name', 'SyncInk Community')
    clean_reason = reason.strip() if reason else "No reason provided"
    
    embed = discord.Embed(
        description=f"You were muted in **{s_name}**. | **{clean_reason}**",
        color=0xE74C3C
    )
    try:
        await member.send(embed=embed)
    except Exception:
        pass

_recent_warn_dms = {}

async def send_warn_dm(member: discord.Member, reason: str = "No reason provided", server_name: str = None, moderator: str = None) -> bool:
    """Sends a standardized official warning notification DM to a member (moderator identity kept confidential). Returns True if successfully sent."""
    now = time.time()
    last_sent = _recent_warn_dms.get(member.id, 0)
    if now - last_sent < 3:
        return True

    _recent_warn_dms[member.id] = now
    s_name = server_name or getattr(member.guild, 'name', 'SyncInk Community')
    clean_reason = reason.strip() if reason else "No reason provided"

    embed = SyncInkEmbed(
        title=f"{Emojis.WARNING} Official Warning",
        color=WARNING_COLOR
    )
    embed.description = (
        f"You have received an official warning in **{s_name}**.\n\n"
        f"• **Reason:** {clean_reason}"
    )

    try:
        await member.send(embed=embed)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False
