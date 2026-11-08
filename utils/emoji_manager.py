import os
import discord
from typing import Dict, List, Optional
from utils.logger import log
from utils.emojis import (
    Emojis,
    EmojiPartials,
    EMOJI_NAME_MAP,
    UNICODE_FALLBACKS,
    VERIFIED_BOT_EMOJI_IDS,
    VERIFIED_BOT_EMOJIS_BY_NAME,
)

class EmojiManager:
    """
    Dynamically discovers, synchronizes, and auto-uploads Application Emojis
    directly to the SyncInk Radio application profile (via bot.fetch_application_emojis
    and bot.create_application_emoji).
    Guarantees cross-server compatibility and completely eliminates raw broken :name: text.
    """

    # Essential application emojis and their candidate filenames in assets/emojis
    EMOJI_ASSET_FILES = {
        "sync_alert": ["sync-alert.gif", "syncink_voice_alert.gif", "sync-warning.gif"],
        "sync_check_yes": ["28943-check-yes2.gif"],
        "refused": ["7047-refused.gif"],
        "approved": ["2122-approved-check-box.gif"],
        "SyncInkAI": ["SyncInkAI.png", "SyncInk-AI.png"],
        "s_arrow": ["s_arrow.png"],
        "arrow": ["arrow.gif"],
        "playbutton": ["playbutton.png", "Play Button.png"],
        "pausebutton": ["pausebutton.png", "pause.png"],
        "previous": ["previous.png", "Previous Track.png"],
        "next": ["next.png", "Next Track.png"],
        "radio": ["radio.png", "Radio.png"],
        "queue": ["queue.png", "Queue.png"],
        "repeat": ["repeat.png"],
        "shuffle": ["shuffle.png"],
        "delete": ["delete.png"],
        "time": ["time.png"],
        "like": ["like.png"],
        "dislike": ["dislike.png"],
        "spotify": ["spotify.png"],
        "youtubemusic": ["youtubemusic.png"],
        "soundcloud": ["soundcloud.png"],
        "applemusic": ["applemusic.png", "apple-music.png"],
        "deezer": ["deezer.png"],
        "tidal": ["tidal.png"],
        "syncinkmusic": ["syncinkmusic.png", "syncink-music.png"],
        "settings": ["settings.gif"],
        "connectionping": ["connectionping.gif"],
        "CPU": ["CPU.png"],
        "developer": ["developer.png"],
        "owner": ["owner.png"],
        "partnered": ["partnered.png"],
        "verified": ["verified.png"],
    }

    # Normalized emoji name -> (Emojis attribute, EmojiPartials attribute)
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
        "sync_alert": ("WARNING", "WARNING"),
        "syncalert": ("ALERT", "ALERT"),
        "syncwarning": ("WARNING", "WARNING"),
        "sync_warning": ("WARNING", "WARNING"),
        "refused": ("REFUSED", "REFUSED"),
        "approved": ("APPROVED", "APPROVED"),
        "sync_check_yes": ("CHECK_YES", "CHECK_YES"),
        "synccheckyes": ("CHECK_YES", "CHECK_YES"),
        "check_yes": ("CHECK_YES", "CHECK_YES"),
        "checkyes": ("CHECK_YES", "CHECK_YES"),
        "loading": ("LOADING", "LOADING"),
        "connectionping": ("CONNECTION_PING", "CONNECTION_PING"),
        "syncrobot": ("SYNCBOT", "SYNCBOT"),
        "syncbot": ("SYNCBOT", "SYNCBOT"),
        "sync_bot": ("SYNCBOT", "SYNCBOT"),
        "syncinkai": ("AI", "AI"),
        "syncink_ai": ("AI", "AI"),
        "ai": ("AI", "AI"),
        "s_arrow": ("S_ARROW", "S_ARROW"),
        "sarrow": ("S_ARROW", "S_ARROW"),
        "arrow": ("ARROW", "ARROW"),
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
        app_emojis: List[discord.Emoji] = []

        # Ensure bot.application_id is set if bot.user is available
        if not getattr(bot, "application_id", None) and getattr(bot, "user", None):
            try:
                bot.application_id = bot.user.id
            except Exception:
                pass

        # 1. Fetch Application Emojis currently uploaded to this bot application
        try:
            if hasattr(bot, "fetch_application_emojis"):
                fetched = await bot.fetch_application_emojis()
                app_emojis = list(fetched)
                log.info(f"[EmojiManager] Fetched {len(app_emojis)} existing application emojis from bot profile.")
        except Exception as e:
            log.warning(f"[EmojiManager] fetch_application_emojis error: {e}")

        existing_names = {
            e.name.lower().replace("-", "_").replace(" ", ""): e for e in app_emojis
        }

        # 2. Automatically upload missing emojis from local assets to bot profile
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidate_dirs = [
            os.path.join(base_dir, "assets", "emojis"),
            r"D:\SyncInk Radio emojies",
            r"D:\SyncInk Support\assets\emojis",
            r"D:\",
        ]

        if hasattr(bot, "create_application_emoji"):
            for target_name, file_candidates in cls.EMOJI_ASSET_FILES.items():
                norm_key = target_name.lower().replace("-", "_").replace(" ", "")
                if norm_key in existing_names:
                    continue

                # Locate image asset file
                found_path = None
                for c_dir in candidate_dirs:
                    if not os.path.isdir(c_dir):
                        continue
                    for f_name in file_candidates:
                        p = os.path.join(c_dir, f_name)
                        if os.path.isfile(p):
                            found_path = p
                            break
                    if found_path:
                        break

                if not found_path:
                    continue

                # Read and upload if within Discord's 256KB limit
                try:
                    file_size = os.path.getsize(found_path)
                    if file_size > 256 * 1024:
                        log.debug(f"[EmojiManager] Skipping '{target_name}': file {found_path} exceeds 256KB ({file_size} bytes)")
                        continue

                    with open(found_path, "rb") as img_file:
                        img_bytes = img_file.read()

                    new_emoji = await bot.create_application_emoji(name=target_name, image=img_bytes)
                    app_emojis.append(new_emoji)
                    existing_names[norm_key] = new_emoji
                    log.info(f"[EmojiManager] Auto-uploaded application emoji '{target_name}' (ID: {new_emoji.id}) to bot application.")
                except discord.HTTPException as he:
                    log.warning(f"[EmojiManager] Discord HTTP error uploading '{target_name}': {he}")
                except Exception as ex:
                    log.warning(f"[EmojiManager] Could not upload '{target_name}': {ex}")

        # 3. Combine with bot's accessible guild emojis
        all_emojis: List[discord.Emoji] = list(app_emojis)
        for guild in getattr(bot, "guilds", []):
            all_emojis.extend(guild.emojis)

        # 4. Update global verified caches in utils.emojis
        VERIFIED_BOT_EMOJI_IDS.clear()
        VERIFIED_BOT_EMOJIS_BY_NAME.clear()

        emoji_obj_by_name: Dict[str, discord.Emoji] = {}
        for emoji in all_emojis:
            VERIFIED_BOT_EMOJI_IDS.add(emoji.id)
            clean_name = emoji.name.lower().replace("-", "_").replace(" ", "")
            tag = str(emoji)
            VERIFIED_BOT_EMOJIS_BY_NAME[clean_name] = tag
            EMOJI_NAME_MAP[clean_name] = tag
            emoji_obj_by_name[clean_name] = emoji

        # Setup standard aliases in verified map
        alias_pairs = [
            ("syncwarning", "sync_alert"),
            ("syncalert", "sync_alert"),
            ("sync_warning", "sync_alert"),
            ("warning", "sync_alert"),
            ("alert", "sync_alert"),
            ("check_yes", "sync_check_yes"),
            ("synccheckyes", "sync_check_yes"),
            ("checkyes", "sync_check_yes"),
            ("sarrow", "s_arrow"),
            ("syncbot", "syncrobot"),
            ("sync_bot", "syncrobot"),
            ("bot", "syncrobot"),
            ("ai", "syncinkai"),
            ("syncink_ai", "syncinkai"),
            ("chatgpt", "syncinkai"),
        ]
        for alias, target in alias_pairs:
            if target in VERIFIED_BOT_EMOJIS_BY_NAME:
                VERIFIED_BOT_EMOJIS_BY_NAME[alias] = VERIFIED_BOT_EMOJIS_BY_NAME[target]
                EMOJI_NAME_MAP[alias] = VERIFIED_BOT_EMOJIS_BY_NAME[target]
                if target in emoji_obj_by_name:
                    emoji_obj_by_name[alias] = emoji_obj_by_name[target]

        # 5. Dynamically bind verified emojis into Emojis and EmojiPartials
        synced_count = 0
        for name_key, (emoji_attr, partial_attr) in cls.MAPPINGS.items():
            if name_key in emoji_obj_by_name:
                em = emoji_obj_by_name[name_key]
                setattr(Emojis, emoji_attr, str(em))
                setattr(EmojiPartials, partial_attr, discord.PartialEmoji(
                    name=em.name,
                    id=em.id,
                    animated=em.animated
                ))
                synced_count += 1
            else:
                # Use clean Unicode fallback if not uploaded
                fallback = UNICODE_FALLBACKS.get(name_key, "⚠️")
                setattr(Emojis, emoji_attr, fallback)
                setattr(EmojiPartials, partial_attr, discord.PartialEmoji(name=fallback))

        # Synchronize core aliases
        if hasattr(Emojis, "WARNING"):
            setattr(Emojis, "ALERT", getattr(Emojis, "WARNING"))
            setattr(EmojiPartials, "ALERT", getattr(EmojiPartials, "WARNING"))
        if hasattr(Emojis, "SYNCBOT"):
            setattr(Emojis, "BOT", getattr(Emojis, "SYNCBOT"))
            setattr(EmojiPartials, "BOT", getattr(EmojiPartials, "SYNCBOT"))
        if hasattr(Emojis, "AI"):
            setattr(Emojis, "CHATGPT", getattr(Emojis, "AI"))
            setattr(EmojiPartials, "CHATGPT", getattr(EmojiPartials, "AI"))

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

        log.info(f"[EmojiManager] Synchronized {synced_count} custom emojis into active UI system. ({len(VERIFIED_BOT_EMOJI_IDS)} verified IDs)")
