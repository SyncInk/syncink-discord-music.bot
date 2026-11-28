import asyncio
import os
import re
import shutil
import time
from dataclasses import dataclass
from typing import Tuple, Any, Callable, Dict, List, Optional
import queue
import threading
import aiohttp
import discord
from utils.logger import log
from utils.emojis import Emojis, EmojiPartials
import discord.opus

try:
    import yt_dlp
except ImportError:
    yt_dlp = None
    log.warning("[Music Service] yt-dlp is not installed. Run ?fixmusic to auto-install dependencies.")

def ensure_opus_loaded() -> bool:
    """Ensures native libopus C library is loaded for smooth, stutter-free Discord voice encoding."""
    if discord.opus.is_loaded():
        return True
    try:
        discord.opus._load_default()
        if discord.opus.is_loaded():
            log.info("[Audio Engine] Native libopus library successfully loaded via default loader.")
            return True
    except Exception as e:
        log.debug(f"[Audio Engine] _load_default: {e}")

    candidates = [
        "libopus-0.x64.dll",
        "libopus.so.0",
        "libopus.so",
        "/data/data/com.termux/files/usr/lib/libopus.so",
        "/usr/lib/x86_64-linux-gnu/libopus.so.0",
        "/usr/lib/aarch64-linux-gnu/libopus.so.0",
        "/usr/local/lib/libopus.so",
        "libopus.dylib",
    ]
    for candidate in candidates:
        try:
            discord.opus.load_opus(candidate)
            if discord.opus.is_loaded():
                log.info(f"[Audio Engine] Native libopus loaded from {candidate}")
                return True
        except Exception:
            continue

    log.warning("[Audio Engine] Could not load native libopus library; software fallback will be used.")
    return False

# Initialize Opus engine immediately on module import
ensure_opus_loaded()

def get_ffmpeg_path() -> str:
    """Finds the best ffmpeg executable available across Termux, Linux, and Windows."""
    env_path = os.getenv("FFMPEG_PATH")
    if env_path and (os.path.exists(env_path) or shutil.which(env_path)):
        return env_path
    candidates = [
        "/data/data/com.termux/files/usr/bin/ffmpeg",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "ffmpeg.exe"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "ffmpeg"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    sys_path = shutil.which("ffmpeg")
    if sys_path:
        return sys_path
    return "ffmpeg"

from services.track_cleaner import clean_track_metadata, clean_title


def format_duration(seconds: Optional[int]) -> str:
    if seconds is None or seconds < 0:
        return "LIVE"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

def parse_time_to_seconds(time_str: str) -> Optional[int]:
    if not time_str:
        return None
    time_str = time_str.strip()
    if time_str.isdigit():
        return int(time_str)
    parts = time_str.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        return None
    return None

RADIO_STATIONS = {
    'lofi': {
        'name': '24/7 Lofi & Chill Beats',
        'genre': 'Lofi Chill / Instrumental',
        'queries': [
            'lofi instrumental song',
            'chillhop instrumental track',
            'jazzy lofi beat song',
            'relaxing lofi song no vocals'
        ],
    },
    'synthwave': {
        'name': '80s Synthwave / Retro Chill',
        'genre': 'Synthwave / Retro 80s',
        'queries': [
            'synthwave instrumental song',
            'retrowave outrun track',
            'chill synthwave song',
            '80s retro electronic track'
        ],
    },
    'coffee': {
        'name': 'Smooth Coffee Shop Jazz',
        'genre': 'Jazz & Acoustic Lounge',
        'queries': [
            'coffee shop jazz song instrumental',
            'smooth jazz track',
            'acoustic cafe instrumental song',
            'relaxing jazz piano track'
        ],
    },
    'sleep': {
        'name': 'Deep Sleep Ambient Music',
        'genre': 'Ambient / Sleep Waves',
        'queries': [
            'deep sleep ambient song',
            'calm ambient track no vocals',
            'soft piano sleep track',
            'peaceful soundscape instrumental song'
        ],
    },
    'gaming': {
        'name': 'NCS EDM Gaming Radio',
        'genre': 'Electronic & Gaming EDM',
        'queries': [
            'gaming edm track',
            'melodic electronic gaming song',
            'drum and bass gaming track',
            'copyright free edm song'
        ],
    },
}

PLATFORM_EMOJIS_MAP = {
    'youtube': Emojis.YOUTUBEMUSIC,
    'youtubemusic': Emojis.YOUTUBEMUSIC,
    'spotify': Emojis.SPOTIFY,
    'applemusic': Emojis.APPLEMUSIC,
    'apple_music': Emojis.APPLEMUSIC,
    'deezer': Emojis.DEEZER,
    'tidal': Emojis.TIDAL,
    'soundcloud': Emojis.SOUNDCLOUD,
    'radio': Emojis.RADIO,
    'arbitrary': Emojis.SYNCINK_MUSIC,
}

@dataclass
class Track:
    title: str
    clean_title: str
    author: str
    duration: Optional[int]
    url: str
    stream_url: str
    thumbnail: Optional[str]
    platform: str
    requested_by: discord.Member
    is_live: bool = False
    is_radio: bool = False
    radio_station_id: Optional[str] = None
    _stream_resolved_at: float = 0.0

    @property
    def formatted_duration(self) -> str:
        return "LIVE" if self.is_live else format_duration(self.duration)

    @property
    def platform_emoji(self) -> str:
        return PLATFORM_EMOJIS_MAP.get(self.platform.lower(), Emojis.SYNCINK_MUSIC)

class GuildMusicQueue:
    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        self.voice_client: Optional[discord.VoiceClient] = None
        self.text_channel: Optional[discord.abc.Messageable] = None
        self.tracks: List[Track] = []
        self.current_track: Optional[Track] = None
        self.history: List[Track] = []
        self.volume: int = 100
        self.repeat_mode: str = "off"  # 'off', 'track', 'queue'
        self.autoplay: bool = False
        self.is_247: bool = False
        self.now_playing_message: Optional[discord.Message] = None
        self.start_time: float = 0.0
        self.paused_at: Optional[float] = None
        self.total_paused_duration: float = 0.0
        self.seek_offset: float = 0.0
        self.active_audio_source: Optional["BufferedAudioSource"] = None
        self.inactivity_task: Optional[asyncio.Task] = None
        self.active_radio_station: Optional[str] = None
        self.active_radio_station_info: Optional[Dict[str, Any]] = None
        self.radio_recent_urls: List[str] = []
        self.radio_menu_url: Optional[str] = None
        self.radio_menu_message: Optional[discord.Message] = None
        self.manual_skip: bool = False
        self.playback_token: int = 0
        self.advance_lock = asyncio.Lock()
        # AI AutoPlay state
        self.prefetched_autoplay_track: Optional[Track] = None
        self.prefetched_autoplay_meta: Optional[Dict[str, Any]] = None
        self.prefetch_task: Optional[asyncio.Task] = None
        self.last_autoplay_meta: Optional[Dict[str, Any]] = None
        self.session_played_history: List[str] = []
        self.session_artists: List[str] = []

    @property
    def size(self) -> int:
        return len(self.tracks)

    def get_playback_time_exact(self, is_playing: Optional[bool] = None, is_paused: Optional[bool] = None) -> float:
        """Returns sub-second audio position locked to delivered 20ms PCM frames (or wall clock fallback)."""
        if not self.current_track:
            return 0.0
        active_src = getattr(self, "active_audio_source", None)
        if active_src is not None and hasattr(active_src, "elapsed_audio_seconds"):
            if not getattr(active_src, "audio_started", False) and self.seek_offset <= 0.0:
                return 0.0
            pos = float(self.seek_offset or 0.0) + float(active_src.elapsed_audio_seconds)
            return max(0.0, pos)
        if self.start_time == 0.0:
            return max(0.0, float(self.seek_offset or 0.0))
        paused = (self.paused_at is not None) if is_paused is None else (bool(is_paused) and self.paused_at is not None)
        if paused:
            active = self.paused_at - self.start_time - self.total_paused_duration
        else:
            active = time.time() - self.start_time - self.total_paused_duration
        return max(0.0, float(self.seek_offset or 0.0) + float(active))

    def get_playback_time(self) -> int:
        return max(0, int(self.get_playback_time_exact()))

    def get_progress_bar(self, width: int = 16) -> str:
        current_sec = self.get_playback_time()
        total_sec = self.current_track.duration if self.current_track else 0
        if not total_sec or self.current_track.is_live:
            return f"{format_duration(current_sec)} ━━━━━━━━🔘━━━━━━━━ LIVE"
        progress = min(1.0, max(0.0, current_sec / total_sec))
        knob_pos = int(progress * width)
        line = ""
        for i in range(width):
            if i == knob_pos:
                line += "🔘"
            else:
                line += "━"
        return f"{format_duration(current_sec)} {line} {format_duration(total_sec)}"

    def cancel_inactivity(self):
        if self.inactivity_task and not self.inactivity_task.done():
            self.inactivity_task.cancel()
        self.inactivity_task = None


class BufferedAudioSource(discord.AudioSource):
    """
    Buffers audio frames in a dedicated background worker thread.
    Absorbs CPU spikes (such as yt-dlp querying metadata for next songs)
    and network jitter, permanently eliminating audio stutter and distortion.
    Also tracks exact 20ms real PCM frames delivered to Discord so timers & lyrics stay frame-locked.
    """
    def __init__(
        self,
        source: discord.AudioSource,
        buffer_size: int = 150,
        on_first_frame: Optional[Callable[[], None]] = None,
    ):
        # 150 frames * 20ms = 3.0 seconds of audio pre-buffering
        self.original = source
        self._buffer: queue.Queue = queue.Queue(maxsize=buffer_size)
        self._stopped = threading.Event()
        self._finished = False
        self._on_first_frame = on_first_frame
        self.real_frames_read: int = 0
        self.audio_started: bool = False

        self._thread = threading.Thread(target=self._fill_buffer, daemon=True)
        self._thread.start()
        self._underrun_count = 0

    @property
    def elapsed_audio_seconds(self) -> float:
        return self.real_frames_read * 0.02

    @property
    def volume(self) -> float:
        return getattr(self.original, "volume", 1.0)

    @volume.setter
    def volume(self, val: float):
        if hasattr(self.original, "volume"):
            self.original.volume = val

    def _fill_buffer(self):
        try:
            while not self._stopped.is_set():
                try:
                    data = self.original.read()
                    if not data:
                        break
                    while not self._stopped.is_set():
                        try:
                            self._buffer.put(data, timeout=0.1)
                            break
                        except queue.Full:
                            continue
                except Exception as e:
                    log.debug(f"[BufferedAudioSource] Reader exit: {e}")
                    break
        finally:
            self._finished = True

    def read(self) -> bytes:
        if self._stopped.is_set():
            return b""
        try:
            data = self._buffer.get_nowait()
            self._underrun_count = 0
            self.real_frames_read += 1
            if not self.audio_started:
                self.audio_started = True
                if self._on_first_frame:
                    cb = self._on_first_frame
                    self._on_first_frame = None
                    try:
                        cb()
                    except Exception:
                        pass
            return data
        except queue.Empty:
            if self._finished:
                return b""
            self._underrun_count += 1
            # If thread has finished or 50 frames (1s) of silence while thread exited, return EOF
            if self._underrun_count > 50 and not self._thread.is_alive():
                self._finished = True
                return b""
            # Buffer underrun safeguard: output 20ms of silence (3840 bytes) without advancing audio clock
            return b"\x00" * 3840

    def cleanup(self):
        self._stopped.set()
        self._finished = True
        try:
            self.original.cleanup()
        except Exception:
            pass
        while not self._buffer.empty():
            try:
                self._buffer.get_nowait()
            except queue.Empty:
                break


class MusicService:
    _instance: Optional['MusicService'] = None

    def __init__(self):
        self.queues: Dict[int, GuildMusicQueue] = {}
        self.ydl_opts = {
            'format': 'bestaudio/bestaudio*/best/ba/b',
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch',
            'extract_flat': False,
            'source_address': '0.0.0.0',
            'skip_download': True,
            'socket_timeout': 10,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
            },
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'mweb', 'web', 'ios'],
                    'lang': ['en'],
                }
            },
            'js_runtimes': {'node': {}},
        }

    @classmethod
    def get_instance(cls) -> 'MusicService':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_queue(self, guild_id: int) -> GuildMusicQueue:
        if guild_id not in self.queues:
            self.queues[guild_id] = GuildMusicQueue(guild_id)
        return self.queues[guild_id]

    def remove_queue(self, guild_id: int):
        if guild_id in self.queues:
            q = self.queues[guild_id]
            q.cancel_inactivity()
            q.tracks.clear()
            q.current_track = None
            del self.queues[guild_id]

    async def resolve_spotify(self, url: str) -> Optional[dict]:
        """Resolves Spotify track title via public Spotify oEmbed API."""
        try:
            oembed_url = f"https://open.spotify.com/oembed?url={url}"
            async with aiohttp.ClientSession() as session:
                async with session.get(oembed_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        title = data.get("title", "")
                        thumbnail = data.get("thumbnail_url")
                        return {"search_query": title, "thumbnail": thumbnail}
        except Exception as e:
            log.warning(f"Spotify oEmbed resolve error: {e}")
        return None

    @staticmethod
    def _score_official_candidate(
        entry: Dict[str, Any],
        query: str,
        expected_duration: Optional[int] = None,
    ) -> float:
        """Scores YouTube search candidates so official studio audio/Topic tracks beat trailers & compilations."""
        title = str(entry.get("title") or "").strip()
        channel = str(entry.get("channel") or entry.get("uploader") or "").strip()
        if not title:
            return -9999.0

        title_low = title.lower()
        channel_low = channel.lower()
        q_low = (query or "").lower()

        banned_terms = (
            "jukebox", "nonstop", "non-stop", "mashup", "slowed", "reverb",
            "nightcore", "8d audio", "bass boosted", "karaoke", "reaction",
            "whatsapp status", "full movie", "trailer", "vlog", "episode",
            "1 hour", "8 hours", "#shorts", "shorts", "ringtone",
        )
        for bad in banned_terms:
            if bad in title_low and bad not in q_low:
                return -9999.0

        dur = entry.get("duration")
        if isinstance(dur, (int, float)) and dur > 0:
            if dur < 25:
                return -9999.0
            if dur > 900 and (not expected_duration or expected_duration < 600):
                return -9999.0

        score = 0.0
        if channel_low.endswith(" - topic") or channel_low == "topic":
            score += 70.0
        if any(lbl in channel_low for lbl in (
            "vevo", "sony music", "t-series", "zee music", "yrf", "tips",
            "universal music", "warner music", "atlantic records", "saregama", "official"
        )):
            score += 30.0
        if "official audio" in title_low:
            score += 26.0
        elif "audio" in title_low:
            score += 14.0
        if "lyric" in title_low:
            score += 10.0
        if ("official video" in title_low or "music video" in title_low or "4k video" in title_low) and "audio" not in title_low:
            score -= 8.0
        for soft_bad in ("cover", "remix", "unplugged", "lofi flip", "live performance"):
            if soft_bad in title_low and soft_bad not in q_low:
                score -= 45.0

        if expected_duration and expected_duration > 20 and isinstance(dur, (int, float)) and dur > 20:
            diff = abs(float(dur) - float(expected_duration))
            if diff <= 3.0:
                score += 80.0
            elif diff <= 7.0:
                score += 55.0
            elif diff <= 15.0:
                score += 20.0
            elif diff > 25.0:
                score -= 85.0

        q_tokens = [tok for tok in re.findall(r"\w+", q_low) if len(tok) >= 2]
        haystack = f"{title_low} {channel_low}"
        for tok in q_tokens:
            if tok in haystack:
                score += 6.0
        return score

    async def search_and_extract(
        self,
        query: str,
        requester: discord.Member,
        platform: str = "auto",
        limit: int = 1,
        prefer_official: bool = False,
        expected_duration: Optional[int] = None,
        expected_title: Optional[str] = None,
        expected_artist: Optional[str] = None,
        expected_artwork: Optional[str] = None,
    ) -> List[Track]:
        """Extracts playable Tracks using yt-dlp with official Spotify API & oEmbed fallback."""
        query = query.strip()
        detected_platform = platform.lower()
        forced_thumbnail = expected_artwork if (expected_artwork and str(expected_artwork).startswith("http")) else None

        # Check for Spotify links / URIs
        from services.spotify import SpotifyResolver
        if SpotifyResolver.is_spotify_url_or_uri(query):
            detected_platform = "spotify"
            try:
                res_type, normalized_tracks, container = await SpotifyResolver.resolve(query, limit=100)
                if normalized_tracks:
                    tracks: List[Track] = []
                    for nt in normalized_tracks:
                        tracks.append(
                            Track(
                                title=nt.title,
                                clean_title=clean_title(nt.title),
                                author=nt.artist,
                                duration=nt.duration_sec,
                                url=nt.original_url,
                                stream_url="",  # Lazy resolution right before playback in refresh_stream_url
                                thumbnail=nt.artwork,
                                platform="spotify",
                                requested_by=requester,
                                is_live=False,
                            )
                        )
                    # If single track, resolve stream immediately for zero-lag start
                    if len(tracks) == 1:
                        try:
                            await self.refresh_stream_url(tracks[0])
                        except Exception as ex:
                            log.warning(f"[Spotify Extract] Immediate stream resolution for '{tracks[0].title}': {ex}")
                    return tracks
            except Exception as se:
                log.warning(f"[Spotify Extract] Spotify resolve error: {se}. Falling back to oEmbed...")

            # Fallback to public oEmbed if Spotify resolver encountered error
            meta = await self.resolve_spotify(query)
            if meta and meta.get("search_query"):
                query = meta["search_query"]
                forced_thumbnail = meta.get("thumbnail")
        elif "soundcloud.com" in query.lower():
            detected_platform = "soundcloud"
        elif "apple.com" in query.lower():
            detected_platform = "applemusic"
        elif "deezer.com" in query.lower():
            detected_platform = "deezer"
        elif "tidal.com" in query.lower():
            detected_platform = "tidal"
        elif "youtube.com" in query.lower() or "youtu.be" in query.lower():
            detected_platform = "youtube"

        search_query = query
        use_official_scoring = (
            prefer_official
            and limit == 1
            and not query.startswith("http://")
            and not query.startswith("https://")
            and detected_platform != "soundcloud"
        )
        if not query.startswith("http://") and not query.startswith("https://"):
            if detected_platform == "soundcloud":
                search_query = f"scsearch{limit}:{query}"
            elif use_official_scoring:
                official_term = query if any(k in query.lower() for k in ("official", "audio", "topic")) else f"{query} official audio"
                search_query = f"ytsearch5:{official_term}"
            else:
                search_query = f"ytsearch{limit}:{query}"

        loop = asyncio.get_event_loop()
        opts = dict(self.ydl_opts)
        q_low = query.lower()
        is_single_fast = (limit <= 1) and (not use_official_scoring) and ("list=" not in q_low) and ("/playlist" not in q_low) and ("/sets/" not in q_low)
        opts['extract_flat'] = False if is_single_fast else 'in_playlist'

        def _extract(opts_to_use):
            if yt_dlp is None:
                raise RuntimeError("yt-dlp is not installed. An administrator can run `?fixmusic` or `pip install yt-dlp` to enable audio playback.")
            with yt_dlp.YoutubeDL(opts_to_use) as ydl:
                return ydl.extract_info(search_query, download=False)

        info = None
        try:
            info = await loop.run_in_executor(None, _extract, opts)
        except Exception as primary_err:
            log.warning(f"[Music Extract] Primary extraction failed for '{search_query}': {primary_err}")
            # Format / client retry with broad format
            fb_opts = dict(opts)
            fb_opts['format'] = 'best/ba/b'
            fb_opts.pop('extractor_args', None)
            try:
                info = await loop.run_in_executor(None, _extract, fb_opts)
            except Exception as fb_err:
                log.warning(f"[Music Extract] Fallback format extraction failed: {fb_err}")
                # If search query is not a direct URL and not soundcloud, attempt soundcloud fallback
                if not query.startswith("http://") and not query.startswith("https://") and detected_platform != "soundcloud":
                    log.info(f"[Music Extract] Attempting SoundCloud fallback for: {query}")
                    sc_query = f"scsearch{limit}:{query}"
                    def _sc_fallback():
                        sc_opts = dict(self.ydl_opts)
                        sc_opts.pop('extractor_args', None)
                        sc_opts['extract_flat'] = 'in_playlist'
                        with yt_dlp.YoutubeDL(sc_opts) as ydl:
                            return ydl.extract_info(sc_query, download=False)
                    try:
                        info = await loop.run_in_executor(None, _sc_fallback)
                        detected_platform = "soundcloud"
                    except Exception as sc_err:
                        log.error(f"[Music Extract] SoundCloud fallback also failed: {sc_err}")
                        raise RuntimeError(f"Audio extraction failed: {primary_err}")
                else:
                    raise RuntimeError(f"Audio extraction failed: {primary_err}")

        if not info:
            return []

        entries = [e for e in (info.get("entries") if "entries" in info else [info]) if e]
        if use_official_scoring and len(entries) > 1:
            entries.sort(
                key=lambda item: self._score_official_candidate(item, query, expected_duration=expected_duration),
                reverse=True,
            )
            entries = [entries[0]]
        tracks: List[Track] = []

        for entry in entries:
            if not entry:
                continue
            raw_title = entry.get("title") or "Unknown Track"
            raw_uploader = entry.get("uploader") or entry.get("artist") or entry.get("channel") or ""
            c_title, c_artist = clean_track_metadata(raw_title, raw_uploader, entry)
            if expected_title:
                raw_title = expected_title
                c_title = clean_title(expected_title) or expected_title
            artist = expected_artist or c_artist
            duration = entry.get("duration") or expected_duration
            raw_url = entry.get("webpage_url") or entry.get("url") or query
            if entry.get("id") and (not isinstance(raw_url, str) or not raw_url.startswith("http")):
                raw_url = f"https://www.youtube.com/watch?v={entry['id']}"
            webpage_url = raw_url
            stream_url = entry.get("url") or webpage_url
            thumb = forced_thumbnail or entry.get("thumbnail")
            if not thumb and entry.get("thumbnails"):
                thumb = entry["thumbnails"][-1].get("url")
            if not thumb and entry.get("id"):
                thumb = f"https://i.ytimg.com/vi/{entry['id']}/hqdefault.jpg"
            is_live = bool(entry.get("is_live", False))

            if not webpage_url:
                continue

            is_direct_stream = (
                isinstance(stream_url, str)
                and stream_url.startswith("http")
                and stream_url != webpage_url
                and "youtube.com/watch" not in stream_url
                and "youtu.be/" not in stream_url
            )
            track = Track(
                title=raw_title,
                clean_title=c_title,
                author=artist,
                duration=duration,
                url=webpage_url,
                stream_url=stream_url,
                thumbnail=thumb,
                platform=detected_platform if detected_platform != "auto" else "youtube",
                requested_by=requester,
                is_live=is_live,
                _stream_resolved_at=time.time() if is_direct_stream else 0.0,
            )
            tracks.append(track)

        return tracks

    async def refresh_stream_url(self, track: Track) -> str:
        """Resolve a fresh media URL immediately before playback (extractor URLs expire)."""
        if track.platform == "radio" or track.is_radio:
            return track.stream_url

        # Skip redundant yt-dlp round-trip if stream URL was freshly resolved in this session
        s_url = getattr(track, "stream_url", "") or ""
        if (
            s_url.startswith("http")
            and s_url != track.url
            and "youtube.com/watch" not in s_url
            and "youtu.be/" not in s_url
            and (time.time() - getattr(track, "_stream_resolved_at", 0.0)) < 120.0
        ):
            return s_url

        if yt_dlp is None:
            raise RuntimeError("yt-dlp is not installed; run ?fixmusic to repair music dependencies.")

        loop = asyncio.get_running_loop()
        opts = dict(self.ydl_opts)
        opts["noplaylist"] = True
        opts["extract_flat"] = False

        # Spotify tracks: resolve stream via authorized audio match using verified title and artist
        if track.platform == "spotify" or "open.spotify.com" in track.url:
            match_query = f"ytsearch1:{track.title} {track.author or ''}".strip()
            def _extract_spotify_stream():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    res = ydl.extract_info(match_query, download=False)
                if res and res.get("entries"):
                    return next((entry for entry in res["entries"] if entry), None)
                return res

            info = None
            try:
                info = await loop.run_in_executor(None, _extract_spotify_stream)
            except Exception as e:
                log.warning(f"[Refresh Stream] Spotify primary stream match failed for '{track.title}': {e}")
                # Fallback to soundcloud search if YouTube match fails
                try:
                    sc_opts = dict(opts)
                    sc_opts.pop('extractor_args', None)
                    with yt_dlp.YoutubeDL(sc_opts) as ydl:
                        sc_info = ydl.extract_info(f"scsearch1:{track.title} {track.author or ''}".strip(), download=False)
                    if sc_info and sc_info.get("entries"):
                        info = next((entry for entry in sc_info["entries"] if entry), None)
                except Exception:
                    pass

            if not info or not info.get("url"):
                raise RuntimeError(f"No authorized playback source could be matched for: {track.title} by {track.author}")

            track.stream_url = info["url"]
            track._stream_resolved_at = time.time()
            track.is_live = bool(info.get("is_live", track.is_live))
            if not track.thumbnail and info.get("thumbnail"):
                track.thumbnail = info["thumbnail"]
            return track.stream_url

        def _do_extract(extract_opts, target_url):
            with yt_dlp.YoutubeDL(extract_opts) as ydl:
                res = ydl.extract_info(target_url, download=False)
            if res and res.get("entries"):
                res = next((entry for entry in res["entries"] if entry), None)
            return res

        info = None
        try:
            info = await loop.run_in_executor(None, _do_extract, opts, track.url)
        except Exception as primary_err:
            log.warning(f"[Refresh Stream] Primary refresh failed on '{track.title}': {primary_err}")
            # Fallback 1: Broad format and web client
            fallback_opts = dict(opts)
            fallback_opts['format'] = 'best/ba/b'
            fallback_opts.pop('extractor_args', None)
            try:
                info = await loop.run_in_executor(None, _do_extract, fallback_opts, track.url)
            except Exception as fb_err:
                log.warning(f"[Refresh Stream] Fallback format failed for '{track.title}': {fb_err}")
                # Fallback 2: Search by title and artist if direct URL failed
                if track.title:
                    fallback_query = f"ytsearch1:{track.title} {track.author or ''}".strip()
                    try:
                        info = await loop.run_in_executor(None, _do_extract, fallback_opts, fallback_query)
                    except Exception:
                        pass

        if not info or not info.get("url"):
            # If all refreshes failed but we already have an existing stream_url, attempt using it
            if track.stream_url and track.stream_url.startswith("http"):
                log.warning(f"[Refresh Stream] Using cached stream_url for {track.title}")
                return track.stream_url
            raise RuntimeError("The source did not return a playable audio stream.")

        track.stream_url = info["url"]
        track._stream_resolved_at = time.time()
        track.is_live = bool(info.get("is_live", track.is_live))
        if info.get("thumbnail"):
            track.thumbnail = info["thumbnail"]
        elif not track.thumbnail and info.get("thumbnails"):
            track.thumbnail = info["thumbnails"][-1].get("url")
        return track.stream_url

    def create_audio_source(
        self,
        track: Track,
        volume: int = 100,
        seek_seconds: float = 0.0,
        on_first_frame: Optional[Callable[[], None]] = None,
    ) -> discord.AudioSource:
        """Constructs an FFmpeg-backed PCMVolumeTransformer with resilient streaming options and memory buffer."""
        ffmpeg_bin = get_ffmpeg_path()
        before_options = (
            "-reconnect 1 "
            "-reconnect_streamed 1 "
            "-reconnect_at_eof 1 "
            "-reconnect_on_network_error 1 "
            "-reconnect_on_http_error 5xx,408,429 "
            "-reconnect_delay_max 5 "
            "-rw_timeout 15000000 "
            "-thread_queue_size 8192 "
            "-probesize 1024k "
            "-analyzeduration 2000000 "
            '-user_agent "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36" '
            "-nostdin"
        )
        if seek_seconds and seek_seconds > 0 and not track.is_radio and not track.is_live:
            before_options = f"-ss {float(seek_seconds):.2f} " + before_options
        options = "-vn -ar 48000 -ac 2 -nostats -loglevel error"

        pcm = discord.FFmpegPCMAudio(
            track.stream_url,
            executable=ffmpeg_bin,
            before_options=before_options,
            options=options
        )
        vol_normalized = max(0.01, min(2.0, volume / 100.0))
        vol_transformed = discord.PCMVolumeTransformer(pcm, volume=vol_normalized)
        return BufferedAudioSource(vol_transformed, buffer_size=150, on_first_frame=on_first_frame)

    async def start_radio_station(
        self,
        voice_channel: discord.VoiceChannel,
        text_channel: discord.abc.Messageable,
        requester: discord.Member,
        station_id: str
    ) -> Track:
        """Starts 24/7 continuous radio streaming for a specific station."""
        station = RADIO_STATIONS.get(station_id, RADIO_STATIONS['lofi'])
        guild_id = voice_channel.guild.id
        queue = self.get_queue(guild_id)
        queue.text_channel = text_channel
        queue.active_radio_station = station_id

        # Pick a fresh query from station
        import random
        queries = station.get("queries", ["lofi beat instrumental"])
        query = random.choice(queries)

        tracks = await self.search_and_extract(query, requester, platform="radio", limit=5)
        if not tracks:
            raise RuntimeError(f"Could not load radio station {station['name']}.")

        # Pick one that wasn't recently played
        selected_track = tracks[0]
        for t in tracks:
            if t.url not in queue.radio_recent_urls:
                selected_track = t
                break

        selected_track.is_radio = True
        selected_track.radio_station_id = station_id
        selected_track.platform = "radio"
        queue.radio_recent_urls.append(selected_track.url)
        if len(queue.radio_recent_urls) > 50:
            queue.radio_recent_urls.pop(0)

        # Clear active upcoming tracks and play immediately
        queue.tracks.clear()
        queue.tracks.append(selected_track)
        return selected_track
