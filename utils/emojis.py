import discord
import re
from typing import Set, Dict

# Set of emoji IDs verified to belong to this bot's application or accessible guilds
# Pre-seeded with verified Audia AI and preference emojis; updated dynamically by EmojiManager upon startup.
VERIFIED_BOT_EMOJI_IDS: Set[int] = {
    1559661648011075664,  # playing (animated)
    1520914584012328961,  # syncwarning (animated)
    1571879222908031078,  # Audia_AI
    1568327108533551144,  # PunjabiPop
    1568327227983007864,  # LofiCoffee
    1568327830981583039,  # Kpop
    1568327695639650464,  # Indieacoustic
    1568327544279662663,  # HipHop
    1568327456434430093,  # EnergetichighBPM
    1568327771501895762,  # EDM
    1568327378504130600,  # Romanticsoulful
    1568357873224781835,  # refresh
    1568355166913167430,  # scale
    1558918836303044688,  # syncinkmusic
}

# Map of normalized emoji names -> verified custom Discord emoji tags (<:name:id> or <a:name:id>)
VERIFIED_BOT_EMOJIS_BY_NAME: Dict[str, str] = {
    "playing": "<a:playing:1559661648011075664>",
    "syncwarning": "<a:syncwarning:1520914584012328961>",
    "sync_alert": "<a:syncwarning:1520914584012328961>",
    "syncalert": "<a:syncwarning:1520914584012328961>",
    "warning": "<a:syncwarning:1520914584012328961>",
    "alert": "<a:syncwarning:1520914584012328961>",
    "audia_ai": "<:Audia_AI:1571879222908031078>",
    "audia": "<:Audia_AI:1571879222908031078>",
    "audiaai": "<:Audia_AI:1571879222908031078>",
    "punjabipop": "<:PunjabiPop:1568327108533551144>",
    "loficoffee": "<:LofiCoffee:1568327227983007864>",
    "kpop": "<:Kpop:1568327830981583039>",
    "indieacoustic": "<:Indieacoustic:1568327695639650464>",
    "hiphop": "<:HipHop:1568327544279662663>",
    "energetichighbpm": "<:EnergetichighBPM:1568327456434430093>",
    "edm": "<:EDM:1568327771501895762>",
    "romanticsoulful": "<:Romanticsoulful:1568327378504130600>",
    "refresh": "<:refresh:1568357873224781835>",
    "scale": "<:scale:1568355166913167430>",
    "syncinkmusic": "<:syncinkmusic:1558918836303044688>",
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
    "audia_ai": "🎧",
    "audia": "🎧",
    "audiaai": "🎧",
    "syncinkai": "🤖",
    "syncink_ai": "🤖",
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
    "volume": "🔊",
    
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
    Defaults to clean, beautiful, universal Unicode emojis so that all messages render flawlessly
    for every user in every server without Discord stripping unowned tags to raw :name: text.
    Dynamically upgraded to verified custom Discord application emojis by EmojiManager upon startup.
    """
    # System Alerts & Notices
    ALERT = "<a:syncwarning:1520914584012328961>"
    WARNING = "<a:syncwarning:1520914584012328961>"
    SETTINGS = "⚙️"
    REFUSED = "❌"
    APPROVED = "✅"
    CHECK_YES = "✅"
    LOADING = "⏳"
    PENDING = "⏳"

    # AI & Core Identity
    AUDIA_AI = "<:Audia_AI:1571879222908031078>"
    AI = "<:Audia_AI:1571879222908031078>"
    CHATGPT = "🤖"
    SYNCBOT = "🤖"
    BOT = "🤖"
    CPU = "💻"
    S_ARROW = "▸"
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
    LIKE = "👍"
    DISLIKE = "👎"
    PLAYING = "<a:playing:1559661648011075664>"
    SCALE = "⚖️"
    REFRESH = "🔄"
    VOLUME = "🔊"

    # Platforms
    SPOTIFY = "🟢"
    YOUTUBEMUSIC = "🔴"
    APPLEMUSIC = "🍎"
    DEEZER = "🎵"
    TIDAL = "🌊"
    SOUNDCLOUD = "🟠"
    SYNCINK_MUSIC = "<:syncinkmusic:1558918836303044688>"

    # Music Genres & Moods
    PUNJABI_POP = "<:PunjabiPop:1568327108533551144>"
    LOFI_COFFEE = "<:LofiCoffee:1568327227983007864>"
    KPOP = "<:Kpop:1568327830981583039>"
    INDIE_ACOUSTIC = "<:Indieacoustic:1568327695639650464>"
    HIP_HOP = "<:HipHop:1568327544279662663>"
    ENERGETIC_HIGH_BPM = "<:EnergetichighBPM:1568327456434430093>"
    EDM = "<:EDM:1568327771501895762>"
    ROMANTIC_SOULFUL = "<:Romanticsoulful:1568327378504130600>"

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
    Defaults to universal Unicode symbols to guarantee buttons and dropdowns never fail or crash.
    Upgraded dynamically by EmojiManager if custom emojis are verified for this application.
    """
    # System Alerts & Notices
    ALERT = discord.PartialEmoji(name="syncwarning", id=1520914584012328961, animated=True)
    WARNING = discord.PartialEmoji(name="syncwarning", id=1520914584012328961, animated=True)
    SETTINGS = discord.PartialEmoji(name="⚙️")
    REFUSED = discord.PartialEmoji(name="❌")
    APPROVED = discord.PartialEmoji(name="✅")
    CHECK_YES = discord.PartialEmoji(name="✅")
    LOADING = discord.PartialEmoji(name="⏳")
    PENDING = discord.PartialEmoji(name="⏳")

    # AI & Navigation
    AUDIA_AI = discord.PartialEmoji(name="Audia_AI", id=1571879222908031078, animated=False)
    AI = discord.PartialEmoji(name="Audia_AI", id=1571879222908031078, animated=False)
    CHATGPT = discord.PartialEmoji(name="🤖")
    SYNCBOT = discord.PartialEmoji(name="🤖")
    BOT = discord.PartialEmoji(name="🤖")
    CPU = discord.PartialEmoji(name="💻")
    S_ARROW = discord.PartialEmoji(name="▸")
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
    LIKE = discord.PartialEmoji(name="👍")
    DISLIKE = discord.PartialEmoji(name="👎")
    PLAYING = discord.PartialEmoji(name="playing", id=1559661648011075664, animated=True)
    SCALE = discord.PartialEmoji(name="scale", id=1568355166913167430, animated=False)
    REFRESH = discord.PartialEmoji(name="refresh", id=1568357873224781835, animated=False)

    # Platforms
    SPOTIFY = discord.PartialEmoji(name="🟢")
    YOUTUBEMUSIC = discord.PartialEmoji(name="🔴")
    APPLEMUSIC = discord.PartialEmoji(name="🍎")
    DEEZER = discord.PartialEmoji(name="🎵")
    TIDAL = discord.PartialEmoji(name="🌊")
    SOUNDCLOUD = discord.PartialEmoji(name="🟠")
    SYNCINK_MUSIC = discord.PartialEmoji(name="syncinkmusic", id=1558918836303044688, animated=False)

    # Genres & Moods
    PUNJABI_POP = discord.PartialEmoji(name="PunjabiPop", id=1568327108533551144, animated=False)
    LOFI_COFFEE = discord.PartialEmoji(name="LofiCoffee", id=1568327227983007864, animated=False)
    KPOP = discord.PartialEmoji(name="Kpop", id=1568327830981583039, animated=False)
    INDIE_ACOUSTIC = discord.PartialEmoji(name="Indieacoustic", id=1568327695639650464, animated=False)
    HIP_HOP = discord.PartialEmoji(name="HipHop", id=1568327544279662663, animated=False)
    ENERGETIC_HIGH_BPM = discord.PartialEmoji(name="EnergetichighBPM", id=1568327456434430093, animated=False)
    EDM = discord.PartialEmoji(name="EDM", id=1568327771501895762, animated=False)
    ROMANTIC_SOULFUL = discord.PartialEmoji(name="Romanticsoulful", id=1568327378504130600, animated=False)

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
    "<a:syncwarning:1547034231438319616>": "<a:syncwarning:1520914584012328961>",
    "<a:syncalert:1547036006455189626>": "<a:syncwarning:1520914584012328961>",
    "<a:sync_alert:1513822294831534220>": "<a:syncwarning:1520914584012328961>",
    "<a:syncwarning:1513822294831534220>": "<a:syncwarning:1520914584012328961>",
    "<a:syncwarning:1573698286941118705>": "<a:syncwarning:1520914584012328961>",
    "<a:sync_alert:1573698286941118705>": "<a:syncwarning:1520914584012328961>",
    "<a:1573698286941118705>": "<a:syncwarning:1520914584012328961>",
    "<a::1573698286941118705>": "<a:syncwarning:1520914584012328961>",
    "<:1573698286941118705>": "<a:syncwarning:1520914584012328961>",
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

    # Replace broken or unverified alert tags & replace 🎶 with animated playing
    text = re.sub(r'<a?:[a-zA-Z0-9_~-]*:1573698286941118705>', '<a:syncwarning:1520914584012328961>', text)
    text = re.sub(r'<a?:1573698286941118705>', '<a:syncwarning:1520914584012328961>', text)
    text = text.replace("🎶", "<a:playing:1559661648011075664>")

    # 4. Filter unverified custom emojis (<a?:name:id>)
    # If the bot is not permitted to send this ID, Discord strips it to :name: text.
    def _replace_custom_tag(match):
        name = match.group(2)
        emoji_id = int(match.group(3))
        name_lower = name.lower().replace("-", "_").replace(" ", "")

        # If verified accessible, keep as high-res custom emoji
        if emoji_id in VERIFIED_BOT_EMOJI_IDS:
            return match.group(0)

        # If we have a verified replacement for this emoji under an owned ID, use that
        if name_lower in VERIFIED_BOT_EMOJIS_BY_NAME:
            cand = VERIFIED_BOT_EMOJIS_BY_NAME[name_lower]
            c_match = re.search(r':(\d+)>', cand)
            if c_match and int(c_match.group(1)) in VERIFIED_BOT_EMOJI_IDS:
                return cand

        # Otherwise fallback to clean Unicode to avoid Discord stripping it to text
        return UNICODE_FALLBACKS.get(name_lower, "⚠️")

    text = re.sub(r'<([a]?):([a-zA-Z0-9_~-]+):(\d+)>', _replace_custom_tag, text)

    # 5. Convert unformatted :name: emojis
    def _replace_colon_name(match):
        name = match.group(1)
        name_lower = name.lower().replace("-", "_").replace(" ", "")

        # Check verified custom emojis first (only if ID is actively verified)
        if name_lower in VERIFIED_BOT_EMOJIS_BY_NAME:
            cand = VERIFIED_BOT_EMOJIS_BY_NAME[name_lower]
            c_match = re.search(r':(\d+)>', cand)
            if c_match and int(c_match.group(1)) in VERIFIED_BOT_EMOJI_IDS:
                return cand

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
            if verified_tag:
                c_match = re.search(r':(\d+)>', verified_tag)
                if c_match and int(c_match.group(1)) in VERIFIED_BOT_EMOJI_IDS:
                    text = text.replace(colon_name, verified_tag)
                    continue
            text = text.replace(colon_name, fallback_symbol)

    # 7. Final strip of backticks around emojis
    text = re.sub(r'[`\x60]+\s*(<a?:[a-zA-Z0-9_~-]+:\d+>)\s*[`\x60]+', r'\1', text)

    return text
