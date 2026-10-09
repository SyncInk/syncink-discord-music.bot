'use strict';

const VARIANT_PATTERNS = [
  /\b(youtube shorts?|shorts? edit|short version)\b/i,
  /\bslowed(?:\s*\+?\s*reverb)?\b/i,
  /\bsped\s*up\b/i,
  /\bnightcore\b/i,
  /\bmashup\b/i,
  /\bcover\b/i,
  /\bkaraoke\b/i,
  /\breaction\b/i,
  /\blyric(?:s| video)\b/i,
  /\b8d audio\b/i,
  /\bloop(?:ed)?\b/i,
  /\bfan ?made\b/i,
  /\bedit\b/i,
  /\bremix\b/i,
  /\breverb\b/i,
];

function normalizeForMatch(value) {
  return String(value || '').toLowerCase()
    .replace(/\[[^\]]*]/g, ' ')
    .replace(/\([^)]*\)/g, ' ')
    .replace(/[^a-z0-9\s]/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function tokenizeForMatch(value) {
  return normalizeForMatch(value).split(' ').map((token) => token.trim()).filter((token) => token.length > 1);
}

function isUrl(value) {
  return /^https?:\/\//i.test(String(value || '').trim()) || /^www\./i.test(String(value || '').trim());
}

function canonicalSongKey(track) {
  const title = String(track?.cleanTitle || track?.title || '')
    .replace(/\b(official\s*(audio|video|music video)|audio|music video|vevo|topic|hd|4k|lyrics?)\b/gi, ' ')
    .replace(/\([^)]*\)|\[[^\]]*]/g, ' ')
    .replace(/\b(feat\.?|ft\.?)\b.*$/i, ' ');
  return normalizeForMatch(title);
}

function cleanTrackTitle(track) {
  return String(track?.cleanTitle || track?.title || 'Unknown Track')
    .replace(/\b(official\s*(audio|video|music video)|lyrics?\s*(video)?|music video|4k|hd)\b/gi, ' ')
    .replace(/\s*[|•·]\s*(official.*|lyrics?.*|music video.*)$/i, ' ')
    .replace(/\s+/g, ' ')
    .trim() || 'Unknown Track';
}

function cleanTrackArtist(track) {
  return String(track?.author || 'Unknown artist')
    .replace(/\s*[-|•·]\s*(topic|vevo|official( artist channel)?)$/i, '')
    .replace(/\s+/g, ' ')
    .trim() || 'Unknown artist';
}

function canonicalResultKey(track) {
  const song = canonicalSongKey(track);
  const artist = normalizeForMatch(String(track?.author || '').replace(/\b(topic|vevo|official audio|official)\b/gi, ' '));
  const duration = Number(track?.durationMS || 0);
  const durationBucket = duration > 0 ? Math.round(duration / 10_000) : 0;
  return `${song}|${artist}|${durationBucket}`;
}

function isUnrequestedVariant(track, rawQuery = '') {
  if (isUrl(rawQuery)) return false;
  const title = String(track?.cleanTitle || track?.title || '');
  const url = String(track?.url || '');
  const query = String(rawQuery || '');
  const durationMs = Number(track?.durationMS || 0);
  if (VARIANT_PATTERNS.some((pattern) => pattern.test(title) && !pattern.test(query))) return true;
  if (/\/shorts?\//i.test(url)) return true;
  return durationMs > 0 && durationMs < 60_000;
}

function matchConfidence(track, rawQuery) {
  if (isUrl(rawQuery)) return 1;
  const queryTokens = [...new Set(tokenizeForMatch(rawQuery))];
  if (!queryTokens.length) return 1;
  const title = normalizeForMatch(track?.cleanTitle || track?.title || '');
  const artist = normalizeForMatch(track?.author || '');
  const combined = `${title} ${artist}`.trim();
  if (!combined) return 0;
  const combinedCoverage = queryTokens.filter((token) => combined.includes(token)).length / queryTokens.length;
  const titleCoverage = queryTokens.filter((token) => title.includes(token)).length / queryTokens.length;
  // A title-only request should match the title; artist-only overlap is weak evidence.
  return Math.min(1, combinedCoverage * 0.65 + titleCoverage * 0.35);
}

function scoreTrackAgainstQuery(track, rawQuery, strictMode = false) {
  const query = normalizeForMatch(rawQuery);
  if (!query) return 0;
  const queryTokens = tokenizeForMatch(query);
  if (!queryTokens.length) return 0;
  const title = normalizeForMatch(track?.cleanTitle || track?.title || '');
  const author = normalizeForMatch(track?.author || '');
  const combined = `${title} ${author}`.trim();
  if (!combined) return 0;

  const matchCount = queryTokens.filter((token) => combined.includes(token)).length;
  const titleMatchCount = queryTokens.filter((token) => title.includes(token)).length;
  let score = (matchCount / queryTokens.length) * 100 + (titleMatchCount / queryTokens.length) * 35;
  if (title === query) score += 150;
  else if (title.startsWith(`${query} `) || title.includes(` ${query} `)) score += 60;

  const requestedVariant = VARIANT_PATTERNS.some((pattern) => pattern.test(rawQuery));
  if (!requestedVariant && VARIANT_PATTERNS.some((pattern) => pattern.test(title))) score -= 80;
  if (/\b(full movie|part \d+\/\d+)\b/i.test(title) && !/\b(movie|full|part)\b/i.test(rawQuery)) score -= 100;
  if (strictMode && matchCount < Math.max(2, Math.floor(queryTokens.length * 0.6))) score -= 100;
  return score;
}

function prioritizeTracksForPlayback(tracks, rawQuery = '', strictMode = false) {
  if (!Array.isArray(tracks)) return [];
  const sourceScore = { youtube: 6, youtubemusic: 6, soundcloud: 5, arbitrary: 3, spotify: 2, apple_music: 2, applemusic: 2 };
  const unique = new Map();
  for (const track of tracks) {
    if (!track?.url || isUnrequestedVariant(track, rawQuery)) continue;
    const confidence = matchConfidence(track, rawQuery);
    if (confidence < 0.55) continue;
    const key = canonicalResultKey(track) || String(track.url);
    const officialSignal = /\b(official|vevo|topic|provided to youtube)\b/i.test(`${track.title} ${track.author}`) ? 10 : 0;
    const quality = scoreTrackAgainstQuery(track, rawQuery, strictMode) + (sourceScore[String(track.source || '').toLowerCase()] ?? 1) + officialSignal;
    const previous = unique.get(key);
    if (!previous || quality > previous.quality) unique.set(key, { track, quality, confidence });
  }
  return [...unique.values()].sort((a, b) => b.quality - a.quality).map(({ track, confidence }) => {
    track.syncinkMatchConfidence = confidence;
    return track;
  });
}

module.exports = { normalizeForMatch, tokenizeForMatch, canonicalSongKey, canonicalResultKey, cleanTrackTitle, cleanTrackArtist, isUnrequestedVariant, matchConfidence, scoreTrackAgainstQuery, prioritizeTracksForPlayback };
