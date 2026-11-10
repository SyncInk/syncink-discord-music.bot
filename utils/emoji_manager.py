import os
import aiohttp
import base64
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
    directly to the SyncInk Radio application profile via Discord API v10 REST.
    Guarantees cross-server compatibility and completely eliminates raw broken :name: text.
    """

    # User-verified custom emojis (populated dynamically from actual API discovery only)
    DEFAULT_KNOWN_EMOJIS = {}

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

        # 1. Resolve Application ID and Token
        app_id = None
        try:
            if hasattr(bot, "application_id") and bot.application_id:
                app_id = bot.application_id
        except Exception:
            pass

        if not app_id and hasattr(bot, "application") and bot.application:
            app_id = bot.application.id

        if not app_id:
            try:
                app_info = await bot.application_info()
                app_id = app_info.id
            except Exception:
                pass

        if not app_id and getattr(bot, "user", None):
            app_id = bot.user.id

        # Internal connection cache
        if app_id and hasattr(bot, "_connection"):
            try:
                bot._connection.application_id = app_id
            except Exception:
                pass

        token = getattr(bot.http, "token", None) or os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")

        # Map of normalized name -> emoji dict {id, name, animated, tag}
        app_emoji_dict: Dict[str, dict] = {}

        # 2. Fetch via Discord API v10 REST
        if app_id and token:
            headers = {
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json"
            }
            url = f"https://discord.com/api/v10/applications/{app_id}/emojis"
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, headers=headers) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                            log.info(f"[EmojiManager] REST: Found {len(items)} existing application emojis for App ID {app_id}.")
                            for it in items:
                                eid = int(it["id"])
                                ename = it["name"]
                                eanim = bool(it.get("animated", False))
                                etag = f"<a:{ename}:{eid}>" if eanim else f"<:{ename}:{eid}>"
                                norm = ename.lower().replace("-", "_").replace(" ", "")
                                app_emoji_dict[norm] = {
                                    "id": eid,
                                    "name": ename,
                                    "animated": eanim,
                                    "tag": etag
                                }
                        else:
                            log.warning(f"[EmojiManager] REST fetch emojis returned HTTP {resp.status}")
            except Exception as fe:
                log.warning(f"[EmojiManager] REST fetch emojis failed: {fe}")

        # Fallback to bot.fetch_application_emojis if REST was empty and library supports it
        if not app_emoji_dict and hasattr(bot, "fetch_application_emojis"):
            try:
                lib_emojis = await bot.fetch_application_emojis()
                for em in lib_emojis:
                    norm = em.name.lower().replace("-", "_").replace(" ", "")
                    app_emoji_dict[norm] = {
                        "id": em.id,
                        "name": em.name,
                        "animated": em.animated,
                        "tag": str(em)
                    }
                log.info(f"[EmojiManager] Library fetch found {len(lib_emojis)} application emojis.")
            except Exception as le:
                log.debug(f"[EmojiManager] Library fetch application emojis error: {le}")

        # 3. Auto-Upload missing emojis directly to application profile
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidate_dirs = [
            os.path.join(base_dir, "assets", "emojis"),
            os.path.join(base_dir, "assets"),
        ]

        if app_id and token:
            headers = {
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json"
            }
            url = f"https://discord.com/api/v10/applications/{app_id}/emojis"
            timeout = aiohttp.ClientTimeout(total=20)
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    for target_name, file_candidates in cls.EMOJI_ASSET_FILES.items():
                        norm_key = target_name.lower().replace("-", "_").replace(" ", "")
                        if norm_key in app_emoji_dict:
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

                        file_size = os.path.getsize(found_path)
                        if file_size > 256 * 1024:
                            log.debug(f"[EmojiManager] Skipping '{target_name}': {found_path} exceeds 256KB")
                            continue

                        try:
                            with open(found_path, "rb") as f:
                                img_bytes = f.read()

                            b64_img = base64.b64encode(img_bytes).decode("utf-8")
                            ext = os.path.splitext(found_path)[1].lower().strip(".")
                            mime = "image/gif" if ext == "gif" else "image/png"
                            data_uri = f"data:{mime};base64,{b64_img}"

                            payload = {
                                "name": target_name,
                                "image": data_uri
                            }
                            async with session.post(url, headers=headers, json=payload) as post_resp:
                                if post_resp.status in (200, 201):
                                    created = await post_resp.json()
                                    eid = int(created["id"])
                                    ename = created["name"]
                                    eanim = bool(created.get("animated", False))
                                    etag = f"<a:{ename}:{eid}>" if eanim else f"<:{ename}:{eid}>"
                                    app_emoji_dict[norm_key] = {
                                        "id": eid,
                                        "name": ename,
                                        "animated": eanim,
                                        "tag": etag
                                    }
                                    log.info(f"[EmojiManager] Auto-uploaded Application Emoji '{target_name}' (ID: {eid}) directly to SyncInk Radio profile!")
                                else:
                                    resp_text = await post_resp.text()
                                    log.warning(f"[EmojiManager] Failed upload '{target_name}': HTTP {post_resp.status} - {resp_text[:120]}")
                        except Exception as up_err:
                            log.warning(f"[EmojiManager] Error uploading '{target_name}': {up_err}")
            except Exception as sess_err:
                log.warning(f"[EmojiManager] Upload session error: {sess_err}")

        # 4. Integrate guild emojis
        for guild in getattr(bot, "guilds", []):
            for gemoji in guild.emojis:
                norm = gemoji.name.lower().replace("-", "_").replace(" ", "")
                if norm not in app_emoji_dict:
                    app_emoji_dict[norm] = {
                        "id": gemoji.id,
                        "name": gemoji.name,
                        "animated": gemoji.animated,
                        "tag": str(gemoji)
                    }

        # 5. Integrate pre-configured known application emojis (user-specified)
        for norm, d in cls.DEFAULT_KNOWN_EMOJIS.items():
            if norm not in app_emoji_dict:
                app_emoji_dict[norm] = d

        # 6. Update global verified registries
        VERIFIED_BOT_EMOJI_IDS.clear()
        VERIFIED_BOT_EMOJIS_BY_NAME.clear()

        for norm, d in app_emoji_dict.items():
            VERIFIED_BOT_EMOJI_IDS.add(d["id"])
            VERIFIED_BOT_EMOJIS_BY_NAME[norm] = d["tag"]
            EMOJI_NAME_MAP[norm] = d["tag"]

        # Setup standard aliases
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
                tag = VERIFIED_BOT_EMOJIS_BY_NAME[target]
                VERIFIED_BOT_EMOJIS_BY_NAME[alias] = tag
                EMOJI_NAME_MAP[alias] = tag
                if target in app_emoji_dict and alias not in app_emoji_dict:
                    app_emoji_dict[alias] = app_emoji_dict[target]

        # 7. Dynamically bind into Emojis and EmojiPartials
        synced_count = 0
        for name_key, (emoji_attr, partial_attr) in cls.MAPPINGS.items():
            if name_key in app_emoji_dict:
                d = app_emoji_dict[name_key]
                setattr(Emojis, emoji_attr, d["tag"])
                setattr(EmojiPartials, partial_attr, discord.PartialEmoji(
                    name=d["name"],
                    id=d["id"],
                    animated=d["animated"]
                ))
                synced_count += 1
            else:
                fallback = UNICODE_FALLBACKS.get(name_key, "⚠️")
                setattr(Emojis, emoji_attr, fallback)
                setattr(EmojiPartials, partial_attr, discord.PartialEmoji(name=fallback))

        # Core aliases
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

        log.info(f"[EmojiManager] Synchronized {synced_count} application emojis into active bot system! ({len(VERIFIED_BOT_EMOJI_IDS)} verified IDs)")
