import asyncio
import re
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple
import aiohttp
from utils.logger import log

DEFAULT_LOGO_URL = "static/radio-bot.jpg"

_GENERIC_AUTHORS = {
    "", "artist", "unknown artist", "various artists", "song", "radio", "unknown"
}
_YT_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|youtube\.com/(?:embed|shorts|live)/)([A-Za-z0-9_-]{11})"
)
_CLEAN_NOISE_RE = re.compile(
    r"\s*[\(\[](?:official|lyrics?|lyrical|audio|video|4k|hd|hq|remastered|full\s*song|slowed|reverb)[^\)\]]*[\)\]]",
    re.IGNORECASE,
)


def is_fallback_artwork(url: Optional[str]) -> bool:
    """Returns True when thumbnail is empty, invalid, or a generic SyncInk fallback logo."""
    if not url or not isinstance(url, str):
        return True
    cleaned = url.strip()
    if not cleaned.startswith(("http://", "https://")):
        return True
    return ("74l9su.png" in cleaned) or ("radio-bot.jpg" in cleaned)


def extract_youtube_poster(url: Optional[str]) -> Optional[str]:
    """Derives the deterministic YouTube high-quality video poster URL from a watch/short link."""
    if not url or not isinstance(url, str):
        return None
    m = _YT_ID_RE.search(url)
    if m:
        return f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg"
    return None


class ArtworkService:
    """
    Resolves and caches official album/track cover posters (iTunes -> Deezer -> YouTube)
    so Listening History, Top Tracks, and player embeds display real track artwork
    instead of falling back to the generic bot icon.
    """
    _cache: Dict[str, Tuple[float, Optional[str]]] = {}
    _MAX_CACHE = 2000
    _POSITIVE_TTL = 43200.0  # 12 hours
    _NEGATIVE_TTL = 600.0    # 10 minutes

    @classmethod
    def _clean_terms(cls, title: str, author: str) -> Tuple[str, str]:
        t = _CLEAN_NOISE_RE.sub("", (title or "").strip())
        t = re.sub(r"\s+", " ", t).strip()
        a = (author or "").strip()
        if a.lower() in _GENERIC_AUTHORS:
            a = ""
        return t, a

    @classmethod
    def _cache_key(cls, title: str, author: str) -> str:
        t, a = cls._clean_terms(title, author)
        return f"{t.lower()}::{a.lower()}"

    @classmethod
    def get_cached(cls, title: str, author: str) -> Tuple[bool, Optional[str]]:
        key = cls._cache_key(title, author)
        entry = cls._cache.get(key)
        if not entry:
            return False, None
        ts, val = entry
        ttl = cls._POSITIVE_TTL if val else cls._NEGATIVE_TTL
        if time.time() - ts > ttl:
            cls._cache.pop(key, None)
            return False, None
        return True, val

    @classmethod
    def set_cached(cls, title: str, author: str, url: Optional[str]) -> None:
        if len(cls._cache) >= cls._MAX_CACHE:
            # Evict oldest quarter cleanly
            oldest = sorted(cls._cache.items(), key=lambda kv: kv[1][0])[: cls._MAX_CACHE // 4]
            for k, _ in oldest:
                cls._cache.pop(k, None)
        cls._cache[cls._cache_key(title, author)] = (time.time(), url)

    @classmethod
    async def _fetch_itunes_poster(
        cls, session: aiohttp.ClientSession, title: str, author: str
    ) -> Optional[str]:
        t, a = cls._clean_terms(title, author)
        if not t:
            return None
        query = f"{a} {t}".strip() if a else t
        url = f"https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=5"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                results = data.get("results") or []
                if not results:
                    return None

                t_tokens = {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) >= 2}
                a_low = a.lower()
                best_item = None
                best_score = -1

                for item in results:
                    it_title = str(item.get("trackName") or "").lower()
                    it_art = str(item.get("artistName") or "").lower()
                    art_url = item.get("artworkUrl100") or item.get("artworkUrl60")
                    if not art_url:
                        continue
                    score = 0
                    if t.lower() in it_title or it_title in t.lower():
                        score += 4
                    else:
                        overlap = sum(1 for tok in t_tokens if tok in it_title)
                        score += overlap
                    if a_low and (a_low in it_art or it_art in a_low):
                        score += 4
                    if score > best_score:
                        best_score = score
                        best_item = art_url

                if not best_item or best_score <= 0:
                    # Still allow top result if iTunes returned a single direct match and no artist conflict
                    if a_low and results:
                        first_art = str(results[0].get("artistName") or "").lower()
                        if a_low not in first_art and first_art not in a_low:
                            return None
                    best_item = results[0].get("artworkUrl100") or results[0].get("artworkUrl60")

                if best_item:
                    return re.sub(r"\d+x\d+bb", "600x600bb", best_item)
        except Exception as e:
            log.debug(f"[ArtworkService iTunes] {e}")
        return None

    @classmethod
    async def _fetch_deezer_poster(
        cls, session: aiohttp.ClientSession, title: str, author: str
    ) -> Optional[str]:
        t, a = cls._clean_terms(title, author)
        if not t:
            return None
        query = f"{a} {t}".strip() if a else t
        url = f"https://api.deezer.com/search?q={urllib.parse.quote(query)}&limit=3"
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                items = data.get("data") or []
                if not items:
                    return None
                album = items[0].get("album") or {}
                cover = album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium")
                if cover and str(cover).startswith("http"):
                    return cover
        except Exception as e:
            log.debug(f"[ArtworkService Deezer] {e}")
        return None

    @classmethod
    async def resolve_official_artwork(
        cls,
        title: str,
        author: str = "",
        track_url: str = "",
        existing_thumb: Optional[str] = None,
        platform: str = "",
        session: Optional[aiohttp.ClientSession] = None,
    ) -> Optional[str]:
        """Resolves official cover artwork URL for a song; returns None if unavailable."""
        if existing_thumb and not is_fallback_artwork(existing_thumb):
            return existing_thumb

        yt_thumb = extract_youtube_poster(track_url)

        # Check live radio stations against RadioService favicons first
        if (platform or "").lower() == "radio":
            try:
                from services.radio_service import RadioService
                r_svc = RadioService.get_instance()
                t_low = (title or "").strip().lower()
                for st in (getattr(r_svc, "stations", None) or []):
                    if isinstance(st, dict) and str(st.get("name", "")).strip().lower() == t_low:
                        fav = st.get("favicon")
                        if fav and not is_fallback_artwork(fav):
                            return fav
                        break
            except Exception:
                pass
            if yt_thumb:
                return yt_thumb
            return None

        hit, cached = cls.get_cached(title, author)
        if hit:
            return cached or yt_thumb

        async def _lookup(cli: aiohttp.ClientSession) -> Optional[str]:
            poster = await cls._fetch_itunes_poster(cli, title, author)
            if not poster:
                poster = await cls._fetch_deezer_poster(cli, title, author)
            return poster

        poster: Optional[str] = None
        if session is not None:
            poster = await _lookup(session)
        else:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2.5)) as cli:
                    poster = await _lookup(cli)
            except Exception:
                poster = None

        cls.set_cached(title, author, poster)
        return poster or yt_thumb

    @classmethod
    async def enrich_records(
        cls,
        records: List[Dict[str, Any]],
        db_conn: Any = None,
        key_title: str = "track_title",
        key_author: str = "track_author",
        key_url: str = "track_url",
        key_thumb: str = "thumbnail_url",
        max_network_lookups: int = 20,
    ) -> None:
        """
        Concurrently resolves official posters for records whose thumbnail is empty or fallback logo.
        Persists resolved URLs back to listening_history rows so subsequent requests are instant.
        """
        if not records:
            return

        need_lookup: List[Tuple[str, str, str, str]] = []
        seen_pairs = set()

        for rec in records:
            if not isinstance(rec, dict):
                continue
            cur_thumb = rec.get(key_thumb)
            if not is_fallback_artwork(cur_thumb):
                continue

            title = str(rec.get(key_title) or "").strip()
            author = str(rec.get(key_author) or "").strip()
            t_url = str(rec.get(key_url) or "").strip()
            plat = str(rec.get("platform") or "").strip().lower()

            yt_thumb = extract_youtube_poster(t_url)
            hit, cached = cls.get_cached(title, author)
            if hit:
                if cached or yt_thumb:
                    rec[key_thumb] = cached or yt_thumb
                continue

            pair_key = cls._cache_key(title, author)
            if pair_key not in seen_pairs and len(need_lookup) < max_network_lookups:
                seen_pairs.add(pair_key)
                need_lookup.append((title, author, t_url, plat))
            elif yt_thumb:
                rec[key_thumb] = yt_thumb

        if need_lookup:
            sem = asyncio.Semaphore(6)
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2.5)) as cli:
                    async def _worker(t: str, a: str, u: str, p: str):
                        async with sem:
                            await cls.resolve_official_artwork(t, a, u, None, p, session=cli)
                    await asyncio.gather(*[_worker(*args) for args in need_lookup], return_exceptions=True)
            except Exception as err:
                log.debug(f"[ArtworkService Enrich Batch] {err}")

        # Apply newly cached results & optionally heal DB rows in background/non-blocking
        db_updates: List[Tuple[int, str]] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            if not is_fallback_artwork(rec.get(key_thumb)):
                continue
            title = str(rec.get(key_title) or "").strip()
            author = str(rec.get(key_author) or "").strip()
            t_url = str(rec.get(key_url) or "").strip()
            _, cached = cls.get_cached(title, author)
            resolved = cached or extract_youtube_poster(t_url)
            if resolved and not is_fallback_artwork(resolved):
                rec[key_thumb] = resolved
                row_id = rec.get("id")
                if isinstance(row_id, int) and 0 < row_id < 800000:
                    db_updates.append((row_id, resolved))

        if db_conn and db_updates:
            for rid, poster_url in db_updates:
                try:
                    await db_conn.execute(
                        "UPDATE listening_history SET thumbnail_url = $1 WHERE id = $2",
                        poster_url,
                        rid,
                    )
                except Exception:
                    pass
