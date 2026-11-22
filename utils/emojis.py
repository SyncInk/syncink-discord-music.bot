import discord
import re
from typing import Set, Dict

# Set of emoji IDs verified to belong to this bot's application or accessible guilds
# Pre-seeded with verified Audia AI, player controls, and custom bot application emojis.
VERIFIED_BOT_EMOJI_IDS: Set[int] = {
    1559661648011075664,  # playing (animated)
    1520914584012328961,  # syncwarning (animated)
    1559185207033077901,  # member
    1558918719881740490,  # Radio
    1558918836303044688,  # syncinkmusic
    1571879222908031078,  # Audia_AI
    1558019502019575918,  # approved (animated)
    1558019488408932423,  # refused (animated)
    1559660676853797005,  # like
    1559660727373930657,  # dislike
    1558917288621777016,  # NextTrack
    1558913195119222814,  # PlayButton
    1558917154294997062,  # Previous
    1558913299221979289,  # pause
    1558916019089575936,  # queue
    1558915041896562860,  # queue_add
    1558916635866308719,  # repeat
    1558914298544136192,  # shuffle
    1568355166913167430,  # scale
    1558918533214380243,  # delete
    1568327108533551144,  # PunjabiPop
    1568327227983007864,  # LofiCoffee
    1568327830981583039,  # Kpop
    1568327695639650464,  # Indieacoustic
    1568327544279662663,  # HipHop
    1568327456434430093,  # EnergetichighBPM
    1568327771501895762,  # EDM
    1568327378504130600,  # Romanticsoulful
    1568357873224781835,  # refresh
}

# Map of normalized emoji names -> verified custom Discord emoji tags (<:name:id> or <a:name:id>)
VERIFIED_BOT_EMOJIS_BY_NAME: Dict[str, str] = {
    "playing": "<a:playing:1559661648011075664>",
    "syncwarning": "<a:syncwarning:1520914584012328961>",
    "sync_alert": "<a:syncwarning:1520914584012328961>",
    "syncalert": "<a:syncwarning:1520914584012328961>",
    "warning": "<a:syncwarning:1520914584012328961>",
    "alert": "<a:syncwarning:1520914584012328961>",
    "member": "<:member:1559185207033077901>",
    "radio": "<:Radio:1558918719881740490>",
    "syncinkmusic": "<:syncinkmusic:1558918836303044688>",
    "syncink_music": "<:syncinkmusic:1558918836303044688>",
    "audia_ai": "<:Audia_AI:1571879222908031078>",
    "audia": "<:Audia_AI:1571879222908031078>",
    "audiaai": "<:Audia_AI:1571879222908031078>",
    "approved": "<a:approved:1558019502019575918>",
    "refused": "<a:refused:1558019488408932423>",
    "like": "<:like:1559660676853797005>",
    "dislike": "<:dislike:1559660727373930657>",
    "nexttrack": "<:NextTrack:1558917288621777016>",
    "next": "<:NextTrack:1558917288621777016>",
    "playbutton": "<:PlayButton:1558913195119222814>",
    "play": "<:PlayButton:1558913195119222814>",
    "play_button": "<:PlayButton:1558913195119222814>",
    "previous": "<:Previous:1558917154294997062>",
    "pause": "<:pause:1558913299221979289>",
    "pausebutton": "<:pause:1558913299221979289>",
    "pause_button": "<:pause:1558913299221979289>",
    "queue": "<:queue:1558916019089575936>",
    "queue_add": "<:queue_add:1558915041896562860>",
    "queueadd": "<:queue_add:1558915041896562860>",
    "repeat": "<:repeat:1558916635866308719>",
    "shuffle": "<:shuffle:1558914298544136192>",
    "scale": "<:scale:1568355166913167430>",
    "delete": "<:delete:1558918533214380243>",
    "punjabipop": "<:PunjabiPop:1568327108533551144>",
    "loficoffee": "<:LofiCoffee:1568327227983007864>",
    "kpop": "<:Kpop:1568327830981583039>",
    "indieacoustic": "<:Indieacoustic:1568327695639650464>",
    "hiphop": "<:HipHop:1568327544279662663>",
    "energetichighbpm": "<:EnergetichighBPM:1568327456434430093>",
    "edm": "<:EDM:1568327771501895762>",
    "romanticsoulful": "<:Romanticsoulful:1568327378504130600>",
    "refresh": "<:refresh:1568357873224781835>",
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
    REFUSED = "<a:refused:1558019488408932423>"
    APPROVED = "<a:approved:1558019502019575918>"
    CHECK_YES = "<a:approved:1558019502019575918>"
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
    PLAY_BUTTON = "<:PlayButton:1558913195119222814>"
    PAUSE_BUTTON = "<:pause:1558913299221979289>"
    PREVIOUS = "<:Previous:1558917154294997062>"
    NEXT = "<:NextTrack:1558917288621777016>"
    QUEUE = "<:queue:1558916019089575936>"
    QUEUE_ADD = "<:queue_add:1558915041896562860>"
    REPEAT = "<:repeat:1558916635866308719>"
    SHUFFLE = "<:shuffle:1558914298544136192>"
    RADIO = "<:Radio:1558918719881740490>"
    SYNCINK_RADIO = "<:Radio:1558918719881740490>"
    DELETE = "<:delete:1558918533214380243>"
    LIKE = "<:like:1559660676853797005>"
    DISLIKE = "<:dislike:1559660727373930657>"
    PLAYING = "<a:playing:1559661648011075664>"
    SCALE = "<:scale:1568355166913167430>"
    REFRESH = "<:refresh:1568357873224781835>"
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
    MEMBERS = "<:member:1559185207033077901>"
    MEMBER = "<:member:1559185207033077901>"
    CANCELLED = "<a:refused:1558019488408932423>"


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
    REFUSED = discord.PartialEmoji(name="refused", id=1558019488408932423, animated=True)
    APPROVED = discord.PartialEmoji(name="approved", id=1558019502019575918, animated=True)
    CHECK_YES = discord.PartialEmoji(name="approved", id=1558019502019575918, animated=True)
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
    PLAY_BUTTON = discord.PartialEmoji(name="PlayButton", id=1558913195119222814, animated=False)
    PAUSE_BUTTON = discord.PartialEmoji(name="pause", id=1558913299221979289, animated=False)
    PREVIOUS = discord.PartialEmoji(name="Previous", id=1558917154294997062, animated=False)
    NEXT = discord.PartialEmoji(name="NextTrack", id=1558917288621777016, animated=False)
    QUEUE = discord.PartialEmoji(name="queue", id=1558916019089575936, animated=False)
    QUEUE_ADD = discord.PartialEmoji(name="queue_add", id=1558915041896562860, animated=False)
    REPEAT = discord.PartialEmoji(name="repeat", id=1558916635866308719, animated=False)
    SHUFFLE = discord.PartialEmoji(name="shuffle", id=1558914298544136192, animated=False)
    RADIO = discord.PartialEmoji(name="Radio", id=1558918719881740490, animated=False)
    SYNCINK_RADIO = discord.PartialEmoji(name="Radio", id=1558918719881740490, animated=False)
    DELETE = discord.PartialEmoji(name="delete", id=1558918533214380243, animated=False)
    LIKE = discord.PartialEmoji(name="like", id=1559660676853797005, animated=False)
    DISLIKE = discord.PartialEmoji(name="dislike", id=1559660727373930657, animated=False)
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
    MEMBERS = discord.PartialEmoji(name="member", id=1559185207033077901, animated=False)
    MEMBER = discord.PartialEmoji(name="member", id=1559185207033077901, animated=False)
    CANCELLED = discord.PartialEmoji(name="refused", id=1558019488408932423, animated=True)


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
    Uses a strict unified token regex to prevent double-replacing inside existing tags.
    """
    if not text:
        return text

    # 1. Clean up malformed or nested tags from past substitutions
    text = re.sub(r'<a?<a:([a-zA-Z0-9_~-]+):(\d+)>:?\d*>', r'<a:\1:\2>', text)
    text = re.sub(r'<a?\s*[:! ]+\s*1520914584012328961>', '<a:syncwarning:1520914584012328961>', text)
    text = re.sub(r'<a?\s*[:! ]+\s*1573698286941118705>', '<a:syncwarning:1520914584012328961>', text)
    text = re.sub(r'<a?:[a-zA-Z0-9_~-]*:1573698286941118705>', '<a:syncwarning:1520914584012328961>', text)
    text = re.sub(r'<a?:1573698286941118705>', '<a:syncwarning:1520914584012328961>', text)

    # 2. Strip backticks around custom emojis <:name:id> or <a:name:id>
    text = re.sub(r'[`\x60]+\s*(<a?:[a-zA-Z0-9_~-]+:\d+>)\s*[`\x60]+', r'\1', text)

    # 3. Strip backticks around raw :name: emojis
    text = re.sub(r'[`\x60]+\s*(:[a-zA-Z0-9_~-]+:)\s*[`\x60]+', r'\1', text)

    # 4. Upgrade legacy tags
    for old_tag, new_tag in OLD_TAG_MAP.items():
        text = text.replace(old_tag, new_tag)

    # Replace 🎶 with animated playing
    text = text.replace("🎶", "<a:playing:1559661648011075664>")

    # 5. Unified single-pass token replacer (custom tags first, standalone colon emojis second)
    token_pattern = re.compile(
        r'(?P<custom><(?P<anim>a)?:(?P<cname>[a-zA-Z0-9_~-]+):(?P<cid>\d+)>)|(?P<colon>:(?P<sname>[a-zA-Z0-9_~-]+):)'
    )

    def _replace_token(match: re.Match) -> str:
        # Case A: Full Discord custom tag (<a?:name:id>)
        if match.group('custom'):
            cid = int(match.group('cid'))
            # If actively verified for this bot, preserve tag untouched
            if cid in VERIFIED_BOT_EMOJI_IDS:
                return match.group('custom')

            cname_lower = match.group('cname').lower().replace("-", "_").replace(" ", "")
            # If known under another verified ID, use that verified tag
            if cname_lower in VERIFIED_BOT_EMOJIS_BY_NAME:
                cand = VERIFIED_BOT_EMOJIS_BY_NAME[cname_lower]
                cand_match = re.search(r':(\d+)>', cand)
                if cand_match and int(cand_match.group(1)) in VERIFIED_BOT_EMOJI_IDS:
                    return cand

            # Otherwise fallback to clean Unicode so Discord doesn't strip it to text
            return UNICODE_FALLBACKS.get(cname_lower, "⚠️")

        # Case B: Standalone :name: emoji
        sname = match.group('sname')
        sname_lower = sname.lower().replace("-", "_").replace(" ", "")

        # Check verified custom emojis
        if sname_lower in VERIFIED_BOT_EMOJIS_BY_NAME:
            cand = VERIFIED_BOT_EMOJIS_BY_NAME[sname_lower]
            cand_match = re.search(r':(\d+)>', cand)
            if cand_match and int(cand_match.group(1)) in VERIFIED_BOT_EMOJI_IDS:
                return cand

        # Check dynamic EMOJI_NAME_MAP
        if sname_lower in EMOJI_NAME_MAP:
            mapped = EMOJI_NAME_MAP[sname_lower]
            c_m = re.match(r'<a?:[a-zA-Z0-9_~-]+:(\d+)>', mapped)
            if c_m:
                if int(c_m.group(1)) in VERIFIED_BOT_EMOJI_IDS:
                    return mapped
            else:
                return mapped

        # Fallback to Unicode
        if sname_lower in UNICODE_FALLBACKS:
            return UNICODE_FALLBACKS[sname_lower]

        return match.group('colon')

    text = token_pattern.sub(_replace_token, text)

    # 6. Final strip of backticks around emojis
    text = re.sub(r'[`\x60]+\s*(<a?:[a-zA-Z0-9_~-]+:\d+>)\s*[`\x60]+', r'\1', text)

    return text
