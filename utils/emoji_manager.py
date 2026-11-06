import discord
from typing import Dict, List, Optional
from utils.logger import log
from utils.emojis import Emojis, EmojiPartials, EMOJI_NAME_MAP, OLD_TAG_MAP

class EmojiManager:
    """
    Dynamically discovers and synchronizes Application Emojis uploaded directly to the
    bot application profile (via bot.fetch_application_emojis) and Guild Emojis.
    Updates Emojis, EmojiPartials, and EMOJI_NAME_MAP dynamically at runtime.
    """
    
    # Mapping of normalized emoji name -> (Emojis attribute, EmojiPartials attribute)
    MAPPINGS = {
        "playbutton": ("PLAY_BUTTON", "PLAY_BUTTON"),
        "pausebutton": ("PAUSE_BUTTON", "PAUSE_BUTTON"),
        "previous": ("PREVIOUS", "PREVIOUS"),
        "next": ("NEXT", "NEXT"),
        "queue": ("QUEUE", "QUEUE"),
        "queueadd": ("QUEUE_ADD", "QUEUE_ADD"),
        "queue_add": ("QUEUE_ADD", "QUEUE_ADD"),
        "repeat": ("REPEAT", "REPEAT"),
        "shuffle": ("SHUFFLE", "SHUFFLE"),
        "radio": ("RADIO", "RADIO"),
        "time": ("TIME", "TIME"),
        "syncinkmusic": ("SYNCINK_MUSIC", "SYNCINK_MUSIC"),
        "syncink_music": ("SYNCINK_MUSIC", "SYNCINK_MUSIC"),
        "youtubemusic": ("YOUTUBEMUSIC", "YOUTUBEMUSIC"),
        "spotify": ("SPOTIFY", "SPOTIFY"),
        "applemusic": ("APPLEMUSIC", "APPLEMUSIC"),
        "deezer": ("DEEZER", "DEEZER"),
        "delete": ("DELETE", "DELETE"),
        "tidal": ("TIDAL", "TIDAL"),
        "looking": ("LOOKING", "LOOKING"),
        "soundcloud": ("SOUNDCLOUD", "SOUNDCLOUD"),
        "like": ("LIKE", "LIKE"),
        "dislike": ("DISLIKE", "DISLIKE"),
        "playing": ("PLAYING", "PLAYING"),
        "syncalert": ("ALERT", "ALERT"),
        "syncwarning": ("WARNING", "WARNING"),
        "refused": ("REFUSED", "REFUSED"),
        "approved": ("APPROVED", "APPROVED"),
        "check_yes": ("CHECK_YES", "CHECK_YES"),
        "loading": ("LOADING", "LOADING"),
        "connectionping": ("CONNECTION_PING", "CONNECTION_PING"),
        "syncbot": ("SYNCBOT", "SYNCBOT"),
        "syncinkai": ("AI", "AI"),
        "s_arrow": ("S_ARROW", "S_ARROW"),
        "sarrow": ("S_ARROW", "S_ARROW"),
        "punjabipop": ("PUNJABI_POP", "PUNJABI_POP"),
        "loficoffee": ("LOFI_COFFEE", "LOFI_COFFEE"),
        "kpop": ("KPOP", "KPOP"),
        "indieacoustic": ("INDIE_ACOUSTIC", "INDIE_ACOUSTIC"),
        "hiphop": ("HIP_HOP", "HIP_HOP"),
        "energetichighbpm": ("ENERGETIC_HIGH_BPM", "ENERGETIC_HIGH_BPM"),
        "edm": ("EDM", "EDM"),
        "romanticsoulful": ("ROMANTIC_SOULFUL", "ROMANTIC_SOULFUL"),
        "refresh": ("REFRESH", "REFRESH"),
        "scale": ("SCALE", "SCALE"),
    }

    @classmethod
    async def sync_application_emojis(cls, bot: discord.Client):
        log.info("[EmojiManager] Synchronizing Application and Bot Profile Emojis...")
        all_emojis = []

        # 1. Fetch Application Emojis directly from the bot application profile
        try:
            if hasattr(bot, "fetch_application_emojis"):
                app_emojis = await bot.fetch_application_emojis()
                log.info(f"[EmojiManager] Successfully fetched {len(app_emojis)} application emojis from bot profile.")
                all_emojis.extend(app_emojis)
        except Exception as e:
            log.warning(f"[EmojiManager] fetch_application_emojis error: {e}")

        # 2. Add guild emojis from bot's guilds as fallback
        for guild in getattr(bot, "guilds", []):
            all_emojis.extend(guild.emojis)

        synced_count = 0
        seen_keys = set()
        for emoji in all_emojis:
            name_lower = emoji.name.lower().replace("-", "_").replace(" ", "")
            tag = str(emoji)
            EMOJI_NAME_MAP[name_lower] = tag

            # Check if this emoji matches our mapped definitions
            if name_lower in cls.MAPPINGS and name_lower not in seen_keys:
                seen_keys.add(name_lower)
                emoji_attr, partial_attr = cls.MAPPINGS[name_lower]
                setattr(Emojis, emoji_attr, tag)
                setattr(EmojiPartials, partial_attr, discord.PartialEmoji(
                    name=emoji.name,
                    id=emoji.id,
                    animated=emoji.animated
                ))
                synced_count += 1

        # Update PLATFORM_EMOJIS_MAP in music_service if loaded
        try:
            from services.music_service import PLATFORM_EMOJIS_MAP
            PLATFORM_EMOJIS_MAP['youtube'] = Emojis.YOUTUBEMUSIC
            PLATFORM_EMOJIS_MAP['youtubemusic'] = Emojis.YOUTUBEMUSIC
            PLATFORM_EMOJIS_MAP['spotify'] = Emojis.SPOTIFY
            PLATFORM_EMOJIS_MAP['applemusic'] = Emojis.APPLEMUSIC
            PLATFORM_EMOJIS_MAP['apple_music'] = Emojis.APPLEMUSIC
            PLATFORM_EMOJIS_MAP['deezer'] = Emojis.DEEZER
            PLATFORM_EMOJIS_MAP['tidal'] = Emojis.TIDAL
            PLATFORM_EMOJIS_MAP['soundcloud'] = Emojis.SOUNDCLOUD
            PLATFORM_EMOJIS_MAP['radio'] = Emojis.RADIO
            PLATFORM_EMOJIS_MAP['arbitrary'] = Emojis.SYNCINK_MUSIC
        except Exception:
            pass

        log.info(f"[EmojiManager] Synchronized {synced_count} application emojis into active UI system.")
