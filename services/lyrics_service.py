import asyncio
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
import aiohttp
from utils.logger import log

_NOISE_BRACKETS_RE = re.compile(
    r"\s*[\(\[](?:official|lyrics?|lyrical|audio|video|music\s*video|hd|4k|hq|remaster(?:ed)?|live|explicit|clean|version|full\s*song|slowed|reverb|visualizer|feat\.?|ft\.?)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)
_FEAT_TAIL_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)
_LRC_TAG_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?\]")
_INLINE_WORD_TIME_RE = re.compile(r"<\d{1,3}:\d{2}(?:\.\d{1,3})?>")
_GENERIC_UPLOADERS = {
    "", "artist", "unknown artist", "various artists", "youtube", "youtube music",
    "t-series", "sony music", "sony music india", "zee music company", "tips official",
    "yrf", "saregama music", "speed records", "desimusicfactory", "vevo",
    "topic", "audio", "radio", "unknown",
}


def clean_lyrics_metadata(title: str, author: str = "") -> Tuple[str, str]:
    """Extracts clean song title and primary artist name for accurate lyrics matching."""
    t = (title or "").strip()
    a = (author or "").strip()

    # Strip channel noise
    a = re.sub(r"\s*-\s*Topic$", "", a, flags=re.IGNORECASE).strip()
    a = re.sub(r"VEVO$", "", a, flags=re.IGNORECASE).strip()
    if a.lower() in _GENERIC_UPLOADERS:
        a = ""

    # Strip bracketed noise like (Official Video), [Lyrics], etc.
    t = _NOISE_BRACKETS_RE.sub("", t).strip()
    t = re.sub(r"\s+", " ", t).strip()

    # If title carries "Artist - Song", split cleanly when author is empty/generic
    if " - " in t:
        parts = [p.strip() for p in t.split(" - ", 1)]
        if parts[0] and parts[1]:
            if not a:
                a = parts[0]
                t = parts[1]
            elif a.lower() in parts[0].lower() or parts[0].lower() in a.lower():
                t = parts[1]

    # Remove trailing " | Movie/Label" segments from Bollywood/YouTube titles
    if "|" in t:
        t = t.split("|", 1)[0].strip()

    t = _FEAT_TAIL_RE.sub("", t).strip()
    a = _FEAT_TAIL_RE.sub("", a).strip()
    return t, a


def parse_lrc(lrc_text: str) -> List[Dict[str, Any]]:
    """
    Parses LRC synchronized lyrics into sorted entries: [{"time": float_seconds, "text": str}].
    Supports multiple timestamps per line and enhanced inline word-timing cleanup.
    """
    if not lrc_text or not isinstance(lrc_text, str):
        return []

    parsed: List[Dict[str, Any]] = []
    for raw_line in lrc_text.splitlines():
        tags = list(_LRC_TAG_RE.finditer(raw_line))
        if not tags:
            continue
        lyric_body = _LRC_TAG_RE.sub("", raw_line)
        lyric_body = _INLINE_WORD_TIME_RE.sub("", lyric_body).strip()
        if not lyric_body:
            # Keep soft instrumental interlude marker only if preceded by vocals
            lyric_body = "♪"
        for m in tags:
            mins = int(m.group(1))
            secs = int(m.group(2))
            frac_raw = m.group(3) or "0"
            # Normalize .xx (centiseconds) vs .xxx (milliseconds)
            if len(frac_raw) <= 2:
                ms = int(frac_raw.ljust(2, "0")) * 10
            else:
                ms = int(frac_raw[:3])
            total_sec = round(mins * 60 + secs + ms / 1000.0, 3)
            parsed.append({"time": total_sec, "text": lyric_body})

    parsed.sort(key=lambda item: item["time"])

    # Collapse consecutive instrumental dots at start/middle cleanly
    compact: List[Dict[str, Any]] = []
    for entry in parsed:
        if entry["text"] == "♪" and (not compact or compact[-1]["text"] == "♪"):
            continue
        compact.append(entry)
    return compact


class LyricsService:
    """
    Asynchronous real-time lyrics service powered by LRCLIB (time-synced LRC)
    with Lyrics.ovh plain-text fallback and in-memory TTL caching.
    """
    _instance: Optional["LyricsService"] = None
    _POSITIVE_TTL = 21600.0  # 6 hours
    _NEGATIVE_TTL = 300.0    # 5 minutes
    _MAX_CACHE = 800

    def __init__(self):
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    @classmethod
    def get_instance(cls) -> "LyricsService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @staticmethod
    def _cache_key(title: str, author: str, duration: int = 0) -> str:
        t, a = clean_lyrics_metadata(title, author)
        return f"{t.lower()}::{a.lower()}::{int(duration or 0) // 10}"

    def get_cached(self, title: str, author: str = "", duration: int = 0) -> Optional[Dict[str, Any]]:
        key = self._cache_key(title, author, duration)
        entry = self._cache.get(key)
        if not entry:
            return None
        ts, payload = entry
        ttl = self._POSITIVE_TTL if payload.get("found") else self._NEGATIVE_TTL
        if time.time() - ts > ttl:
            self._cache.pop(key, None)
            return None
        return payload

    def set_cached(self, title: str, author: str, duration: int, payload: Dict[str, Any]) -> None:
        if len(self._cache) >= self._MAX_CACHE:
            oldest = sorted(self._cache.items(), key=lambda kv: kv[1][0])[: self._MAX_CACHE // 4]
            for k, _ in oldest:
                self._cache.pop(k, None)
        self._cache[self._cache_key(title, author, duration)] = (time.time(), payload)

    @staticmethod
    def _build_result_from_lrclib(item: Dict[str, Any], fallback_title: str, fallback_author: str) -> Dict[str, Any]:
        synced_raw = (item.get("syncedLyrics") or "").strip()
        plain_raw = (item.get("plainLyrics") or "").strip()
        is_inst = bool(item.get("instrumental", False))

        lines = parse_lrc(synced_raw) if synced_raw else []
        if not plain_raw and lines:
            plain_raw = "\n".join(line["text"] for line in lines if line["text"] != "♪")
        plain_lines = [ln.strip() for ln in plain_raw.splitlines() if ln.strip()] if plain_raw else []

        has_lyrics = bool(lines or plain_lines)
        return {
            "found": has_lyrics,
            "synced": bool(lines),
            "instrumental": is_inst and not has_lyrics,
            "track_title": (item.get("trackName") or fallback_title or "Unknown Track").strip(),
            "artist_name": (item.get("artistName") or fallback_author or "Unknown Artist").strip(),
            "album_name": (item.get("albumName") or "").strip(),
            "duration": int(item.get("duration") or 0),
            "source": "LRCLIB",
            "lines": lines,
            "plain_lines": plain_lines,
            "plain_lyrics": plain_raw,
        }

    @classmethod
    async def _query_lrclib_exact(
        cls,
        session: aiohttp.ClientSession,
        track_name: str,
        artist_name: str,
        duration: int = 0,
    ) -> Optional[Dict[str, Any]]:
        if not track_name or not artist_name:
            return None
        params: Dict[str, str] = {
            "track_name": track_name,
            "artist_name": artist_name,
        }
        if duration and duration > 0:
            params["duration"] = str(int(duration))
        url = f"https://lrclib.net/api/get?{urllib.parse.urlencode(params)}"
        headers = {"User-Agent": "SyncInkRadio/3.3 (https://syncink.site)"}
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, dict) and (data.get("syncedLyrics") or data.get("plainLyrics") or data.get("instrumental")):
                        return cls._build_result_from_lrclib(data, track_name, artist_name)
        except Exception as err:
            log.debug(f"[LyricsService LRCLIB get] {err}")
        return None

    @classmethod
    async def _query_lrclib_search(
        cls,
        session: aiohttp.ClientSession,
        query: str,
        target_title: str,
        target_artist: str,
        duration: int = 0,
    ) -> Optional[Dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return None
        url = f"https://lrclib.net/api/search?{urllib.parse.urlencode({'q': q})}"
        headers = {"User-Agent": "SyncInkRadio/3.3 (https://syncink.site)"}
        try:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return None
                items = await resp.json()
                if not isinstance(items, list) or not items:
                    return None

                t_low = (target_title or "").lower()
                a_low = (target_artist or "").lower()
                best_item = None
                best_score = -1.0

                for it in items[:15]:
                    if not isinstance(it, dict):
                        continue
                    has_sync = bool((it.get("syncedLyrics") or "").strip())
                    has_plain = bool((it.get("plainLyrics") or "").strip())
                    if not (has_sync or has_plain):
                        continue

                    score = 0.0
                    if has_sync:
                        score += 50.0
                    elif has_plain:
                        score += 15.0

                    it_title = str(it.get("trackName") or "").lower()
                    it_artist = str(it.get("artistName") or "").lower()
                    if t_low and (t_low == it_title or t_low in it_title or it_title in t_low):
                        score += 20.0
                    if a_low and (a_low == it_artist or a_low in it_artist or it_artist in a_low):
                        score += 15.0

                    it_dur = float(it.get("duration") or 0)
                    if duration > 0 and it_dur > 0:
                        diff = abs(duration - it_dur)
                        if diff <= 3:
                            score += 25.0
                        elif diff <= 8:
                            score += 15.0
                        elif diff > 25:
                            score -= 20.0

                    if score > best_score:
                        best_score = score
                        best_item = it

                if best_item:
                    return cls._build_result_from_lrclib(best_item, target_title or q, target_artist)
        except Exception as err:
            log.debug(f"[LyricsService LRCLIB search] {err}")
        return None

    @classmethod
    async def _query_lyrics_ovh(
        cls,
        session: aiohttp.ClientSession,
        track_name: str,
        artist_name: str,
    ) -> Optional[Dict[str, Any]]:
        if not track_name or not artist_name:
            return None
        safe_artist = urllib.parse.quote(artist_name, safe="")
        safe_title = urllib.parse.quote(track_name, safe="")
        url = f"https://api.lyrics.ovh/v1/{safe_artist}/{safe_title}"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                raw = (data.get("lyrics") or "").strip() if isinstance(data, dict) else ""
                if not raw:
                    return None
                plain_lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                if not plain_lines:
                    return None
                return {
                    "found": True,
                    "synced": False,
                    "instrumental": False,
                    "track_title": track_name,
                    "artist_name": artist_name,
                    "album_name": "",
                    "duration": 0,
                    "source": "Lyrics.ovh",
                    "lines": [],
                    "plain_lines": plain_lines,
                    "plain_lyrics": "\n".join(plain_lines),
                }
        except Exception as err:
            log.debug(f"[LyricsService Lyrics.ovh] {err}")
        return None

    async def get_lyrics(
        self,
        title: str,
        author: str = "",
        duration: int = 0,
    ) -> Dict[str, Any]:
        """Resolves synced (LRC) or plain lyrics for a track title/artist/query."""
        c_title, c_artist = clean_lyrics_metadata(title, author)
        if not c_title:
            return {
                "found": False,
                "synced": False,
                "instrumental": False,
                "track_title": title or "Unknown Track",
                "artist_name": author or "Unknown Artist",
                "album_name": "",
                "duration": int(duration or 0),
                "source": "none",
                "lines": [],
                "plain_lines": [],
                "plain_lyrics": "",
            }

        cached = self.get_cached(c_title, c_artist, duration)
        if cached is not None:
            return dict(cached)

        result: Optional[Dict[str, Any]] = None
        timeout = aiohttp.ClientTimeout(total=4.5)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # 1. Exact match when artist and title are known
                if c_artist:
                    result = await self._query_lrclib_exact(session, c_title, c_artist, duration)
                # 2. If exact failed (or no artist provided), run ranked search
                if not result or not result.get("found"):
                    q = f"{c_title} {c_artist}".strip() if c_artist else c_title
                    searched = await self._query_lrclib_search(session, q, c_title, c_artist, duration)
                    if searched and searched.get("found"):
                        result = searched
                    elif result is None and searched is not None:
                        result = searched
                # 3. Title-only search fallback in case noisy author poisoned search
                if (not result or not result.get("found")) and c_artist:
                    searched_title = await self._query_lrclib_search(session, c_title, c_title, c_artist, duration)
                    if searched_title and searched_title.get("found"):
                        result = searched_title
                # 4. Lyrics.ovh plain-text fallback
                if (not result or not result.get("found")) and c_artist:
                    ovh = await self._query_lyrics_ovh(session, c_title, c_artist)
                    if ovh and ovh.get("found"):
                        result = ovh
        except Exception as err:
            log.debug(f"[LyricsService Error] {err}")

        if not result:
            result = {
                "found": False,
                "synced": False,
                "instrumental": False,
                "track_title": c_title,
                "artist_name": c_artist or "Artist",
                "album_name": "",
                "duration": int(duration or 0),
                "source": "none",
                "lines": [],
                "plain_lines": [],
                "plain_lyrics": "",
            }

        self.set_cached(c_title, c_artist, duration, result)
        return dict(result)
