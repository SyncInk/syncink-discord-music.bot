import discord
import re
from typing import Set, Dict

# Set of emoji IDs verified to belong to this bot's application or accessible guilds
VERIFIED_BOT_EMOJI_IDS: Set[int] = {
    1513822294831534220,  # sync_alert
    1518997998128988160,  # sync_check_yes
    1558019488408932423,  # refused
    1558019502019575918,  # approved
    1568405549572165703,  # SyncInkAI
    1568408148463718490,  # s_arrow
    1538932141273120828,  # syncrobot
    1559660676853797005,  # like
    1559660727373930657,  # dislike
}

# Map of normalized emoji names -> verified custom Discord emoji tags (<:name:id> or <a:name:id>)
VERIFIED_BOT_EMOJIS_BY_NAME: Dict[str, str] = {
    "sync_alert": "<a:sync_alert:1513822294831534220>",
    "syncwarning": "<a:sync_alert:1513822294831534220>",
    "syncalert": "<a:sync_alert:1513822294831534220>",
    "sync_warning": "<a:sync_alert:1513822294831534220>",
    "warning": "<a:sync_alert:1513822294831534220>",
    "alert": "<a:sync_alert:1513822294831534220>",
    "sync_check_yes": "<a:sync_check_yes:1518997998128988160>",
    "synccheckyes": "<a:sync_check_yes:1518997998128988160>",
    "check_yes": "<a:sync_check_yes:1518997998128988160>",
    "checkyes": "<a:sync_check_yes:1518997998128988160>",
    "approved": "<a:approved:1558019502019575918>",
    "refused": "<a:refused:1558019488408932423>",
    "cancelled": "<a:refused:1558019488408932423>",
    "syncinkai": "<:SyncInkAI:1568405549572165703>",
    "syncink_ai": "<:SyncInkAI:1568405549572165703>",
    "ai": "<:SyncInkAI:1568405549572165703>",
    "chatgpt": "<:SyncInkAI:1568405549572165703>",
    "s_arrow": "<:s_arrow:1568408148463718490>",
    "sarrow": "<:s_arrow:1568408148463718490>",
    "syncrobot": "<:syncrobot:1538932141273120828>",
    "syncbot": "<:syncrobot:1538932141273120828>",
    "bot": "<:syncrobot:1538932141273120828>",
    "like": "<:like:1559660676853797005>",
    "dislike": "<:dislike:1559660727373930657>",
}

# Universal, high-compatibility visual Unicode fallbacks
UNICODE_FALLBACKS: Dict[str, str] = {
    # Alerts & Status
    "warning": "⚠️",
    "alert": "⚠️",
    "syncalert": "⚠️",
    "sync_alert": "⚠️",
    "syncwarning": "⚠️",
    "sync_warning": "⚠️",
    "check_yes": "✅",
    "synccheckyes": "✅",
    "sync_check_yes": "✅",
    "checkyes": "✅",
    "approved": "✅",
    "refused": "❌",
    "cancelled": "❌",
    "syncinkai": "🤖",
    "ai": "🤖",
    "chatgpt": "🤖",
    "syncrobot": "🤖",
    "syncbot": "🤖",
    "bot": "🤖",
    "s_arrow": "▸",
    "sarrow": "▸",
    "arrow": "➜",
    "settings": "⚙️",
    "loading": "⏳",
    "pending": "⏳",
    "time": "⏱️",
    
    # Audio Controls
    "playbutton": "▶️",
    "pausebutton": "⏸️",
    "previous": "⏮️",
    "next": "⏭️",
    "queue": "📜",
    "queueadd": "➕",
    "queue_add": "➕",
    "repeat": "🔁",
    "shuffle": "🔀",
    "radio": "📻",
    "syncinkradio": "📻",
    "delete": "🗑️",
    "like": "👍",
    "dislike": "👎",
    "playing": "🎶",
    "scale": "⚖️",
    "refresh": "🔄",
    
    # Platforms & Music Genres
    "spotify": "🟢",
    "youtubemusic": "🔴",
    "soundcloud": "🟠",
    "applemusic": "🍎",
    "deezer": "🎵",
    "tidal": "🌊",
    "syncinkmusic": "🎵",
    "syncink_music": "🎵",
    "punjabipop": "🔥",
    "punjabi_pop": "🔥",
    "loficoffee": "☕",
    "lofi_coffee": "☕",
    "kpop": "✨",
    "indieacoustic": "🎸",
    "indie_acoustic": "🎸",
    "hiphop": "🎤",
    "hip_hop": "🎤",
    "energetichighbpm": "⚡",
    "energetic_high_bpm": "⚡",
    "edm": "🎧",
    "romanticsoulful": "💖",
    "romantic_soulful": "💖",
    
    # Roles & Identity
    "role_owner": "👑",
    "owner": "👑",
    "sync_owner": "👑",
    "role_manager": "💼",
    "admin": "💼",
    "sync_admin": "💼",
    "role_developer": "💻",
    "developer": "💻",
    "role_staff": "🛡️",
    "staff": "🛡️",
    "role_partner": "🤝",
    "partnered": "🤝",
    "partner": "🤝",
    "role_verified": "☑️",
    "verified": "☑️",
    "role_booster": "💎",
    "booster": "💎",
    "experience": "⭐",
    "region": "🌐",
    "argument": "💬",
    "cpu": "💻",
    "looking": "🔍",
    "rules": "📜",
    "terms": "📋",
    "syncink_lock": "🔒",
    "syncinksuggestion": "💡",
    "syncinkquestion": "❓",
    "members": "👥",
    "member": "👤",
}


class Emojis:
    """
    Centralized emoji registry for SyncInk Radio.
    Defaults to verified custom Discord application emojis.
    Dynamically upgraded or synced with application emojis by EmojiManager upon startup.
    """
    # System Alerts & Notices
    ALERT = "<a:sync_alert:1513822294831534220>"
    WARNING = "<a:sync_alert:1513822294831534220>"
    SETTINGS = "⚙️"
    REFUSED = "<a:refused:1558019488408932423>"
    APPROVED = "<a:approved:1558019502019575918>"
    CHECK_YES = "<a:sync_check_yes:1518997998128988160>"
    LOADING = "⏳"
    PENDING = "⏳"

    # AI & Core Identity
    AI = "<:SyncInkAI:1568405549572165703>"
    CHATGPT = "<:SyncInkAI:1568405549572165703>"
    SYNCBOT = "<:syncrobot:1538932141273120828>"
    BOT = "<:syncrobot:1538932141273120828>"
    CPU = "💻"
    S_ARROW = "<:s_arrow:1568408148463718490>"
    ARROW = "➜"
    TIME = "⏱️"
    LOOKING = "🔍"

    # Audio Controls
    PLAY_BUTTON = "▶️"
    PAUSE_BUTTON = "⏸️"
    PREVIOUS = "⏮️"
    NEXT = "⏭️"
    QUEUE = "📜"
    QUEUE_ADD = "➕"
    REPEAT = "🔁"
    SHUFFLE = "🔀"
    RADIO = "📻"
    SYNCINK_RADIO = "📻"
    DELETE = "🗑️"
    LIKE = "<:like:1559660676853797005>"
    DISLIKE = "<:dislike:1559660727373930657>"
    PLAYING = "🎶"
    SCALE = "⚖️"
    REFRESH = "🔄"

    # Platforms
    SPOTIFY = "🟢"
    YOUTUBEMUSIC = "🔴"
    APPLEMUSIC = "🍎"
    DEEZER = "🎵"
    TIDAL = "🌊"
    SOUNDCLOUD = "🟠"
    SYNCINK_MUSIC = "🎵"

    # Music Genres & Moods
    PUNJABI_POP = "🔥"
    LOFI_COFFEE = "☕"
    KPOP = "✨"
    INDIE_ACOUSTIC = "🎸"
    HIP_HOP = "🎤"
    ENERGETIC_HIGH_BPM = "⚡"
    EDM = "🎧"
    ROMANTIC_SOULFUL = "💖"

    # Roles & Server
    ROLE_OWNER = "👑"
    ROLE_MANAGER = "💼"
    ROLE_DEVELOPER = "💻"
    ROLE_STAFF = "🛡️"
    ROLE_PARTNER = "🤝"
    ROLE_VERIFIED = "☑️"
    ROLE_BOOSTER = "💎"
    EXPERIENCE = "⭐"
    REGION = "🌐"
    ARGUMENT = "💬"
    NEON_HEART = "💜"
    HEART_POP = "💖"
    SCRIBBLE_HEART = "💓"
    PURPLE_HEART_EXCLAIM = "❣️"
    PENGUBONK = "🐧"
    EARTH_BLURPLE = "🌍"
    CONNECTION_GOOD = "🟢"
    CONNECTION_MODERATE = "🟡"
    CONNECTION_LOW = "🟠"
    CONNECTION_NONE = "🔴"
    CONNECTION_PING = "📶"
    RULES = "📜"
    TERMS = "📋"
    LOCK = "🔒"
    SUGGESTION = "💡"
    QUESTION = "❓"
    SYNCINK_LOGO = "📻"
    MEMBERS = "👥"
    MEMBER = "👤"
    CANCELLED = "❌"


class EmojiPartials:
    """
    discord.PartialEmoji instances for interactive UI components (Buttons, Select Menus).
    Initialized with verified application emojis. Upgraded dynamically by EmojiManager.
    """
    # System Alerts & Notices
    ALERT = discord.PartialEmoji(name="sync_alert", id=1513822294831534220, animated=True)
    WARNING = discord.PartialEmoji(name="sync_alert", id=1513822294831534220, animated=True)
    SETTINGS = discord.PartialEmoji(name="⚙️")
    REFUSED = discord.PartialEmoji(name="refused", id=1558019488408932423, animated=True)
    APPROVED = discord.PartialEmoji(name="approved", id=1558019502019575918, animated=True)
    CHECK_YES = discord.PartialEmoji(name="sync_check_yes", id=1518997998128988160, animated=True)
    LOADING = discord.PartialEmoji(name="⏳")
    PENDING = discord.PartialEmoji(name="⏳")

    # AI & Navigation
    AI = discord.PartialEmoji(name="SyncInkAI", id=1568405549572165703, animated=False)
    CHATGPT = discord.PartialEmoji(name="SyncInkAI", id=1568405549572165703, animated=False)
    SYNCBOT = discord.PartialEmoji(name="syncrobot", id=1538932141273120828, animated=False)
    BOT = discord.PartialEmoji(name="syncrobot", id=1538932141273120828, animated=False)
    CPU = discord.PartialEmoji(name="💻")
    S_ARROW = discord.PartialEmoji(name="s_arrow", id=1568408148463718490, animated=False)
    ARROW = discord.PartialEmoji(name="➜")
    TIME = discord.PartialEmoji(name="⏱️")
    LOOKING = discord.PartialEmoji(name="🔍")

    # Audio Controls
    PLAY_BUTTON = discord.PartialEmoji(name="▶️")
    PAUSE_BUTTON = discord.PartialEmoji(name="⏸️")
    PREVIOUS = discord.PartialEmoji(name="⏮️")
    NEXT = discord.PartialEmoji(name="⏭️")
    QUEUE = discord.PartialEmoji(name="📜")
    QUEUE_ADD = discord.PartialEmoji(name="➕")
    REPEAT = discord.PartialEmoji(name="🔁")
    SHUFFLE = discord.PartialEmoji(name="🔀")
    RADIO = discord.PartialEmoji(name="📻")
    SYNCINK_RADIO = discord.PartialEmoji(name="📻")
    DELETE = discord.PartialEmoji(name="🗑️")
    LIKE = discord.PartialEmoji(name="like", id=1559660676853797005, animated=False)
    DISLIKE = discord.PartialEmoji(name="dislike", id=1559660727373930657, animated=False)
    PLAYING = discord.PartialEmoji(name="🎶")
    SCALE = discord.PartialEmoji(name="⚖️")
    REFRESH = discord.PartialEmoji(name="🔄")

    # Platforms
    SPOTIFY = discord.PartialEmoji(name="🟢")
    YOUTUBEMUSIC = discord.PartialEmoji(name="🔴")
    APPLEMUSIC = discord.PartialEmoji(name="🍎")
    DEEZER = discord.PartialEmoji(name="🎵")
    TIDAL = discord.PartialEmoji(name="🌊")
    SOUNDCLOUD = discord.PartialEmoji(name="🟠")
    SYNCINK_MUSIC = discord.PartialEmoji(name="🎵")

    # Genres & Moods
    PUNJABI_POP = discord.PartialEmoji(name="🔥")
    LOFI_COFFEE = discord.PartialEmoji(name="☕")
    KPOP = discord.PartialEmoji(name="✨")
    INDIE_ACOUSTIC = discord.PartialEmoji(name="🎸")
    HIP_HOP = discord.PartialEmoji(name="🎤")
    ENERGETIC_HIGH_BPM = discord.PartialEmoji(name="⚡")
    EDM = discord.PartialEmoji(name="🎧")
    ROMANTIC_SOULFUL = discord.PartialEmoji(name="💖")

    # Roles
    ROLE_OWNER = discord.PartialEmoji(name="👑")
    ROLE_MANAGER = discord.PartialEmoji(name="💼")
    ROLE_DEVELOPER = discord.PartialEmoji(name="💻")
    ROLE_STAFF = discord.PartialEmoji(name="🛡️")
    ROLE_PARTNER = discord.PartialEmoji(name="🤝")
    ROLE_VERIFIED = discord.PartialEmoji(name="☑️")
    ROLE_BOOSTER = discord.PartialEmoji(name="💎")
    NEON_HEART = discord.PartialEmoji(name="💜")
    HEART_POP = discord.PartialEmoji(name="💖")
    SCRIBBLE_HEART = discord.PartialEmoji(name="💓")
    PURPLE_HEART_EXCLAIM = discord.PartialEmoji(name="❣️")
    PENGUBONK = discord.PartialEmoji(name="🐧")
    EARTH_BLURPLE = discord.PartialEmoji(name="🌍")
    CONNECTION_PING = discord.PartialEmoji(name="📶")
    RULES = discord.PartialEmoji(name="📜")
    TERMS = discord.PartialEmoji(name="📋")
    LOCK = discord.PartialEmoji(name="🔒")
    SUGGESTION = discord.PartialEmoji(name="💡")
    QUESTION = discord.PartialEmoji(name="❓")
    MEMBERS = discord.PartialEmoji(name="👥")
    MEMBER = discord.PartialEmoji(name="👤")
    CANCELLED = discord.PartialEmoji(name="❌")


# Legacy emoji tags map
OLD_TAG_MAP = {
    "<:SyncProductSupport:1522287691792912394>": "<:SyncProductSupport:1553532855278116956>",
    "<:userreport:1513336966681460856>": "<:accsvr:1553532858058936424>",
    "<:accsvr:1513336966681460856>": "<:accsvr:1553532858058936424>",
    "<:bugreport:1513337174148513892>": "<:bugreport:1553532860408012850>",
    "<:staffabuse:1513337285024677899>": "<:staffabuse:1553532862945562754>",
    "<:others~1:1513337572078911488>": "<:others:1553533697364598814>",
    "<:others:1513337572078911488>": "<:others:1553533697364598814>",
    "<:SyncPartnership:1522289808599290006>": "<:SyncPartnership:1553532869950046340>",
    "<a:7049earthblurple:1558803274813935666>": "<a:earthblurple:1558803274813935666>",
    "<a:approved:1547035150964236379>": "<a:approved:1558019502019575918>",
    "<a:refused:1547035200926654624>": "<a:refused:1558019488408932423>",
    "<:SyncInkAI:1549154093421826058>": "<:SyncInkAI:1568405549572165703>",
    "<:s_arrow:1558799699102793801>": "<:s_arrow:1568408148463718490>",
    "<a:syncwarning:1547034231438319616>": "<a:sync_alert:1513822294831534220>",
    "<a:syncalert:1547036006455189626>": "<a:sync_alert:1513822294831534220>",
    "<a:check_yes:1547034079076032512>": "<a:sync_check_yes:1518997998128988160>",
    "<:syncbot:1552437282059980810>": "<:syncrobot:1538932141273120828>",
}

# Runtime name map initialized with Unicode fallbacks; populated dynamically by EmojiManager
EMOJI_NAME_MAP: Dict[str, str] = {k: v for k, v in UNICODE_FALLBACKS.items()}


def format_discord_emojis(text: str) -> str:
    """
    Scans text for raw emoji names (e.g. :syncwarning:, :s_arrow:, :SyncInkAI:) and
    replaces them with active, verified custom Discord emoji tags (<:name:id>).
    If custom emojis are unverified or cross-application (which Discord would strip to raw text),
    replaces them with clean universal Unicode symbols so raw colons (:name:) NEVER appear in chat.
    Also strips any surrounding backticks (`...`).
    """
    if not text:
        return text

    # 1. Strip backticks around custom emojis <:name:id> or <a:name:id>
    text = re.sub(r'[`\x60]+\s*(<a?:[a-zA-Z0-9_~-]+:\d+>)\s*[`\x60]+', r'\1', text)

    # 2. Strip backticks around raw :name: emojis
    text = re.sub(r'[`\x60]+\s*(:[a-zA-Z0-9_~-]+:)\s*[`\x60]+', r'\1', text)

    # 3. Upgrade legacy tags
    for old_tag, new_tag in OLD_TAG_MAP.items():
        text = text.replace(old_tag, new_tag)

    # 4. Filter unverified custom emojis (<a?:name:id>)
    # If the bot is not permitted to send this ID, Discord strips it to :name: text.
    def _replace_custom_tag(match):
        name = match.group(2)
        emoji_id = int(match.group(3))
        name_lower = name.lower().replace("-", "_").replace(" ", "")

        # If verified accessible, keep as high-res custom emoji
        if emoji_id in VERIFIED_BOT_EMOJI_IDS:
            return match.group(0)

        # If we have a verified replacement for this emoji under a new ID, use that
        if name_lower in VERIFIED_BOT_EMOJIS_BY_NAME:
            return VERIFIED_BOT_EMOJIS_BY_NAME[name_lower]

        # Otherwise fallback to clean Unicode to avoid Discord stripping it to text
        return UNICODE_FALLBACKS.get(name_lower, "⚠️")

    text = re.sub(r'<([a]?):([a-zA-Z0-9_~-]+):(\d+)>', _replace_custom_tag, text)

    # 5. Convert unformatted :name: emojis
    def _replace_colon_name(match):
        name = match.group(1)
        name_lower = name.lower().replace("-", "_").replace(" ", "")

        # Check verified custom emojis first
        if name_lower in VERIFIED_BOT_EMOJIS_BY_NAME:
            return VERIFIED_BOT_EMOJIS_BY_NAME[name_lower]

        # Check dynamic EMOJI_NAME_MAP
        if name_lower in EMOJI_NAME_MAP:
            mapped = EMOJI_NAME_MAP[name_lower]
            custom_match = re.match(r'<a?:[a-zA-Z0-9_~-]+:(\d+)>', mapped)
            if custom_match:
                if int(custom_match.group(1)) in VERIFIED_BOT_EMOJI_IDS:
                    return mapped
            else:
                return mapped

        # Fallback to Unicode
        if name_lower in UNICODE_FALLBACKS:
            return UNICODE_FALLBACKS[name_lower]

        return match.group(0)

    # Matches :name: when NOT part of <:name:id> or <a:name:id>
    text = re.sub(r'(?<!<a:)(?<!<:):([a-zA-Z0-9_~-]+):(?![\d]+>)', _replace_colon_name, text)

    # 6. Safety catch for common reported broken emojis to prevent any text leaks
    safety_replacements = {
        ":syncwarning:": Emojis.WARNING,
        ":syncalert:": Emojis.WARNING,
        ":sync_alert:": Emojis.WARNING,
        ":sync_warning:": Emojis.WARNING,
        ":warning:": Emojis.WARNING,
        ":alert:": Emojis.ALERT,
        ":SyncInkAI:": Emojis.AI,
        ":syncinkai:": Emojis.AI,
        ":s_arrow:": Emojis.S_ARROW,
        ":sarrow:": Emojis.S_ARROW,
        ":check_yes:": Emojis.CHECK_YES,
        ":sync_check_yes:": Emojis.CHECK_YES,
        ":synccheckyes:": Emojis.CHECK_YES,
        ":checkyes:": Emojis.CHECK_YES,
        ":refused:": Emojis.REFUSED,
        ":cancelled:": Emojis.REFUSED,
        ":approved:": Emojis.APPROVED,
        ":syncbot:": Emojis.SYNCBOT,
        ":syncrobot:": Emojis.SYNCBOT,
        ":bot:": Emojis.SYNCBOT,
        ":like:": Emojis.LIKE,
        ":dislike:": Emojis.DISLIKE,
    }
    for colon_name, fallback_symbol in safety_replacements.items():
        if colon_name in text:
            name_key = colon_name.strip(":").lower().replace("-", "_")
            verified_tag = VERIFIED_BOT_EMOJIS_BY_NAME.get(name_key)
            replacement = verified_tag if verified_tag else fallback_symbol
            text = text.replace(colon_name, replacement)

    # 7. Final strip of backticks around emojis
    text = re.sub(r'[`\x60]+\s*(<a?:[a-zA-Z0-9_~-]+:\d+>)\s*[`\x60]+', r'\1', text)

    return text
