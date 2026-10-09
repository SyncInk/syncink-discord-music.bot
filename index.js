'use strict';

require('dotenv').config();

// Railway blocks the ytdl update check sometimes, which can stall a stream with a 403.
process.env.YTDL_NO_UPDATE = process.env.YTDL_NO_UPDATE || '1';
process.env.YOUTUBE_DL_SKIP_PYTHON_CHECK = process.env.YOUTUBE_DL_SKIP_PYTHON_CHECK || '1';

const YOUTUBE_NOISE_PATTERNS = [
  '[YOUTUBEJS][Text]: Unable to find matching run for command run. Skipping...',
  '[YOUTUBEJS][Parser]: ParsingError: Type mismatch',
];

function shouldSuppressYoutubeNoise(args) {
  if (process.env.PLAYER_DEBUG === 'true') return false;
  const first = String(args?.[0] || '');
  return YOUTUBE_NOISE_PATTERNS.some((pattern) => first.includes(pattern));
}

const originalConsoleWarn = console.warn.bind(console);
console.warn = (...args) => {
  if (shouldSuppressYoutubeNoise(args)) return;
  originalConsoleWarn(...args);
};

const originalConsoleError = console.error.bind(console);
console.error = (...args) => {
  if (shouldSuppressYoutubeNoise(args)) return;
  originalConsoleError(...args);
};

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { monitorEventLoopDelay } = require('node:perf_hooks');
const { exec } = require('node:child_process');
const {
  Client,
  GatewayIntentBits,
  Events,
  REST,
  Routes,
  SlashCommandBuilder,
  PermissionFlagsBits,
  EmbedBuilder,
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  MessageFlags,
  ContainerBuilder,
  SectionBuilder,
  TextDisplayBuilder,
  SeparatorBuilder,
  SeparatorSpacingSize,
  ThumbnailBuilder,
} = require('discord.js');
const { Player, QueueRepeatMode, QueryType, QueryResolver, onBeforeCreateStream } = require('discord-player');
const { DefaultExtractors } = require('@discord-player/extractor');
const { MusicTaste } = require('./taste');

// Configure audio encoder priority for mobile ARM / Termux performance
let opusRuntime = null;
try {
  const dpOpus = (opusRuntime = require('@discord-player/opus'));
  if (typeof dpOpus.removeLibopusProvider === 'function') {
    // Deprioritize pure-JS opusscript so mediaplex (Rust native) and @evan/opus (WASM SIMD) are preferred
    dpOpus.removeLibopusProvider('opusscript');
    dpOpus.addLibopusProvider(['opusscript', (mod) => ({ Encoder: mod })]);
    console.log('[Audio Engine] Native/WASM Opus providers are preferred; pure-JS Opus is last-resort only.');
  }
} catch (opusErr) {
  console.warn('[Audio Engine] Could not customize Opus provider order:', opusErr.message || opusErr);
}

let bundledFfmpegPath = null;
try {
  bundledFfmpegPath = require('ffmpeg-static');
} catch {
  bundledFfmpegPath = null;
}

let YoutubeiExtractor = null;
try {
  ({ YoutubeiExtractor } = require('discord-player-youtubei'));
} catch {
  YoutubeiExtractor = null;
}

let ytdl = null;
try {
  ytdl = require('@distube/ytdl-core');
} catch {
  ytdl = null;
}

const YOUTUBEI_EXTRACTOR_ID = 'com.retrouser955.discord-player.discord-player-youtubei';
const YOUTUBEI_SEARCH_ENGINE = `ext:${YOUTUBEI_EXTRACTOR_ID}`;
let isYoutubeiReady = false;

const YTDL_REQUEST_HEADERS = {
  'User-Agent':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  'Accept-Language': 'en-US,en;q=0.9',
};

const BRAND_NAME = 'SyncInk Radio';
const BRAND_COLOR = 0x8a2be2; // SyncInk Signature Cyber Violet (#8A2BE2) matching the glowing logo
const SUCCESS_COLOR = 0x2ecc71; // Neon Emerald
const WARNING_COLOR = 0xf39c12; // Cyber Amber
const ERROR_COLOR = 0xe74c3c; // Refused Crimson
const BRAND_LOGO_URL = 'https://cdn.discordapp.com/emojis/1558021213547139103.png';

const MAX_QUEUE_PREVIEW = 10;
const MAX_PLAYLIST_LOAD = 25;
const MAX_AUTOCOMPLETE_CHOICES = 10;

const BUTTON_IDS = {
  PAUSE_RESUME: 'syncink_pause_resume',
  PREVIOUS: 'syncink_previous',
  SKIP: 'syncink_skip',
  STOP: 'syncink_stop',
  QUEUE: 'syncink_queue',
  LIKE: 'syncink_like',
  PLAYLIST: 'syncink_playlist',
};

const TOKEN = process.env.DISCORD_TOKEN;

function inferClientIdFromToken(token) {
  const firstSegment = token?.split('.')?.[0];
  if (!firstSegment) return null;

  try {
    const decoded = Buffer.from(firstSegment, 'base64').toString('utf8').trim();
    return /^\d{17,20}$/.test(decoded) ? decoded : null;
  } catch {
    return null;
  }
}

function normalizeSnowflake(value) {
  if (!value) return null;
  const asText = String(value).trim();
  return /^\d{17,20}$/.test(asText) ? asText : null;
}

function toBoolean(value, defaultValue = false) {
  if (value == null) return defaultValue;
  const normalized = String(value).trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(normalized)) return true;
  if (['0', 'false', 'no', 'off'].includes(normalized)) return false;
  return defaultValue;
}

// Disabled by default because hosted IPs are often blocked by YouTube on direct ytdl streams.
const ENABLE_DIRECT_YTDL_STREAM = toBoolean(process.env.ENABLE_DIRECT_YTDL_STREAM, false);
const STRICT_SONG_MODE_DEFAULT = toBoolean(process.env.STRICT_SONG_MODE_DEFAULT, false);

function isLikelyUrl(value) {
  const raw = String(value || '').trim();
  if (!raw) return false;

  if (/^https?:\/\//i.test(raw)) return true;

  try {
    const parsed = new URL(raw.startsWith('www.') ? `https://${raw}` : raw);
    return Boolean(parsed.hostname && parsed.hostname.includes('.'));
  } catch {
    return false;
  }
}

function isValidYouTubeStreamUrl(url) {
  if (!ENABLE_DIRECT_YTDL_STREAM || !ytdl || !url) return false;

  try {
    return ytdl.validateURL(url);
  } catch {
    return false;
  }
}

const CLIENT_ID =
  normalizeSnowflake(process.env.DISCORD_CLIENT_ID) ||
  normalizeSnowflake(process.env.CLIENT_ID) ||
  inferClientIdFromToken(TOKEN) ||
  null;

const GUILD_ID = normalizeSnowflake(process.env.DISCORD_GUILD_ID) || normalizeSnowflake(process.env.GUILD_ID) || null;
const PORT = Number(process.env.PORT || 3000);
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const FAVORITES_PATH = path.join(DATA_DIR, 'favorites.json');
const TASTE_PROFILES_PATH = path.join(DATA_DIR, 'taste-profiles.json');
const DEFAULT_AUTOPLAY = toBoolean(process.env.DEFAULT_AUTOPLAY, true);
const OPENAI_API_KEY = process.env.OPENAI_API_KEY || '';
const OPENAI_MODEL = process.env.OPENAI_MODEL || 'gpt-6-astra';
const musicTaste = new MusicTaste({
  filePath: TASTE_PROFILES_PATH,
  apiKey: OPENAI_API_KEY,
  model: OPENAI_MODEL,
});

if (!TOKEN) {
  throw new Error('Missing DISCORD_TOKEN in .env');
}

const PLATFORM_CONFIG = {
  auto: {
    label: 'Auto',
    searchEngine: QueryType.AUTO_SEARCH,
    decorateQuery(query) {
      if (isLikelyUrl(query)) return query;
      return `${query} official audio`;
    },
  },
  youtube: {
    label: 'YouTube',
    searchEngine: QueryType.YOUTUBE_SEARCH,
    decorateQuery(query) {
      if (isLikelyUrl(query)) return query;
      return `${query} official audio`;
    },
  },
  youtubemusic: {
    label: 'YouTube Music',
    searchEngine: QueryType.YOUTUBE_SEARCH,
    decorateQuery(query) {
      if (isLikelyUrl(query)) return query;
      return `${query} official audio`;
    },
  },
  spotify: {
    label: 'Spotify',
    searchEngine: QueryType.SPOTIFY_SEARCH,
    decorateQuery(query) {
      return query;
    },
  },
  applemusic: {
    label: 'Apple Music',
    searchEngine: QueryType.APPLE_MUSIC_SEARCH,
    decorateQuery(query) {
      return query;
    },
  },
  soundcloud: {
    label: 'SoundCloud',
    searchEngine: QueryType.SOUNDCLOUD_SEARCH,
    decorateQuery(query) {
      return query;
    },
  },
  deezer: {
    label: 'Deezer',
    searchEngine: QueryType.AUTO_SEARCH,
    decorateQuery(query) {
      return `deezer ${query}`;
    },
  },
  tidal: {
    label: 'TIDAL',
    searchEngine: QueryType.AUTO_SEARCH,
    decorateQuery(query) {
      return `tidal ${query}`;
    },
  },
};

const SOURCE_LABELS = {
  youtube: 'YouTube',
  youtubemusic: 'YouTube Music',
  soundcloud: 'SoundCloud',
  spotify: 'Spotify',
  apple_music: 'Apple Music',
  applemusic: 'Apple Music',
  deezer: 'Deezer',
  tidal: 'TIDAL',
  arbitrary: 'Direct audio',
};

const EMOJIS = {
  // Brand
  syncink: process.env.EMOJI_SYNCINK || '<:syncink:1558021213547139103>',
  syncinkmusic: process.env.EMOJI_SYNCINK_MUSIC || '<:syncinkmusic:1558020048122159134>',

  // Playback Controls
  play: process.env.EMOJI_PLAY || '<:PlayButton:1558035554942058496>',
  pause: process.env.EMOJI_PAUSE || '<:pause:1558035977371525161>',
  skip: process.env.EMOJI_SKIP || '<:SkipForward:1558034232802824263>',
  previous: process.env.EMOJI_PREVIOUS || '<:PreviousTrack:1558030065361616996>',
  stop: process.env.EMOJI_STOP || '<:delete:1558023146932797472>',

  // Navigation & Library
  queue: process.env.EMOJI_QUEUE || '<:Queue:1558027632740798494>',
  playlist: process.env.EMOJI_PLAYLIST || '<:Playlist:1558037461853016105>',
  added: process.env.EMOJI_ADDED || '<:AddedtoQueue:1558028136166334514>',
  radio: process.env.EMOJI_RADIO || '<:Radio:1558037823976644619>',
  time: process.env.EMOJI_TIME || '<:time:1558035061608026202>',
  heart: process.env.EMOJI_HEART || '<:neonheart:1558023683719561327>',
  volume: process.env.EMOJI_VOLUME || '<:syncvolume:1558019646572204102>',
  members: process.env.EMOJI_MEMBERS || '<:members:1558037851231354900>',
  arrow: process.env.EMOJI_ARROW || '<:arrow:1558022729578450994>',
  looking: process.env.EMOJI_LOOKING || '<:looking:1558019394238681119>',

  // Status & Feedback
  approved: process.env.EMOJI_APPROVED || '<:approved:1558019502019575918>',
  refused: process.env.EMOJI_REFUSED || '<:refused:1558019488408932423>',
  warning: process.env.EMOJI_WARNING || '<:syncwarning:1558019427524677654>',

  // Platforms
  spotify: process.env.EMOJI_SPOTIFY || '<:spotify:1558020457960308737>',
  youtube: process.env.EMOJI_YOUTUBE || '<:youtubemusic:1558020636322828298>',
  youtubemusic: process.env.EMOJI_YOUTUBE_MUSIC || '<:youtubemusic:1558020636322828298>',
  applemusic: process.env.EMOJI_APPLE_MUSIC || '<:applemusic:1558021838494367804>',
  apple_music: process.env.EMOJI_APPLE_MUSIC || '<:applemusic:1558021838494367804>',
  soundcloud: process.env.EMOJI_SOUNDCLOUD || '<:soundcloud:1558021492636123147>',
  deezer: process.env.EMOJI_DEEZER || '<:deezer:1558021038733004820>',
  tidal: process.env.EMOJI_TIDAL || '<:tidal:1558020823975989248>',
  arbitrary: process.env.EMOJI_DIRECT_AUDIO || '<:syncinkmusic:1558020048122159134>',
};

const PLATFORM_EMOJIS = {
  youtube: EMOJIS.youtubemusic,
  youtubemusic: EMOJIS.youtubemusic,
  soundcloud: EMOJIS.soundcloud,
  spotify: EMOJIS.spotify,
  apple_music: EMOJIS.applemusic,
  applemusic: EMOJIS.applemusic,
  deezer: EMOJIS.deezer,
  tidal: EMOJIS.tidal,
  arbitrary: EMOJIS.syncinkmusic,
};

const CONTROL_EMOJIS = {
  pauseResume: EMOJIS.pause,
  skip: EMOJIS.skip,
  stop: EMOJIS.stop,
  like: EMOJIS.heart,
  playlist: EMOJIS.playlist,
};

const FALLBACK_PLATFORM_EMOJIS = {
  youtube: '▶️', youtubemusic: '▶️', soundcloud: '☁️', spotify: '🟢', apple_music: '🍎', applemusic: '🍎',
  deezer: '💜', tidal: '⬛', arbitrary: '🎵',
};

const client = new Client({
  intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildVoiceStates],
});

const resolvedFFmpegPath = process.env.FFMPEG_PATH || bundledFfmpegPath || undefined;
if (resolvedFFmpegPath) {
  process.env.FFMPEG_PATH = resolvedFFmpegPath;
}

const player = new Player(client, {
  ffmpegPath: resolvedFFmpegPath,
  connectionTimeout: 30_000,
  lagMonitor: 60_000,
  skipFFmpeg: true,
});
const eventLoopDelay = monitorEventLoopDelay({ resolution: 20 });
eventLoopDelay.enable();

function probeOpusEngine() {
  if (!opusRuntime?.OpusEncoder) return 'unavailable';
  let encoder;
  try {
    encoder = new opusRuntime.OpusEncoder({ frameSize: 960, channels: 2, rate: 48_000 });
    return opusRuntime.OpusEncoder.type || 'unresolved';
  } catch (error) {
    return `unavailable (${error.message || error})`;
  } finally {
    if (typeof encoder?.destroy === 'function') encoder.destroy();
    else encoder?.delete?.();
  }
}

// Keep the ordinary path as source Opus passthrough: decoding, changing the
// volume, and encoding again costs CPU on small Termux devices and can lower
// fidelity. A queue opts into DSP/FFmpeg only when a user enables a feature.
function createPlaybackNodeOptions(metadata) {
  return {
    metadata,
    leaveOnEmpty: true,
    leaveOnEmptyCooldown: 60_000,
    leaveOnEnd: false,
    leaveOnStop: true,
    leaveOnStopCooldown: 10_000,
    skipOnNoStream: true,
    bufferingTimeout: 15_000,
    verifyFallbackStream: true,
    preferBridgedMetadata: true,
    volume: 100,
    connectionTimeout: 45_000,
    disableVolume: true,
    disableEqualizer: true,
    disableFilterer: true,
    disableBiquad: true,
    disableResampler: true,
    disableCompressor: true,
    disableSeeker: true,
    disableReverb: true,
  };
}

const nowPlayingRegistry = new Map();
const searchSessions = new Map();
const guildMessageCooldowns = new Map();
const playCommandCooldowns = new Map();
const lastTrackStartTimes = new Map();
const strictModeByGuild = new Map();
const streamRecoveryCooldowns = new Map();
const twentyFourSevenGuilds = new Set();
const emptyVcTimers = new Map();
const radioStationsByGuild = new Map();
const radioRecentTrackUrls = new Map();
const radioFillLocks = new Map();

const RADIO_STATIONS = {
  lofi: {
    name: '☕ Lofi & Chill Beats',
    genre: 'Lofi Chill / Instrumental',
    queries: ['lofi instrumental song', 'chillhop instrumental track', 'jazzy lofi beat song', 'relaxing lofi song no vocals'],
  },
  synthwave: {
    name: '🌆 Synthwave / Retro Chill Radio',
    genre: 'Synthwave / Retro 80s',
    queries: ['synthwave instrumental song', 'retrowave outrun track', 'chill synthwave song', '80s retro electronic track'],
  },
  coffee: {
    name: '🎷 Smooth Coffee Shop Jazz',
    genre: 'Jazz & Acoustic Lounge',
    queries: ['coffee shop jazz song instrumental', 'smooth jazz track', 'acoustic cafe instrumental song', 'relaxing jazz piano track'],
  },
  sleep: {
    name: '🌙 Deep Sleep Ambient Music',
    genre: 'Ambient / Sleep Waves',
    queries: ['deep sleep ambient song', 'calm ambient track no vocals', 'soft piano sleep track', 'peaceful soundscape instrumental song'],
  },
  gaming: {
    name: '⚡ NCS EDM Gaming Radio',
    genre: 'Electronic & Gaming EDM',
    queries: ['gaming edm track', 'melodic electronic gaming song', 'drum and bass gaming track', 'copyright free edm song'],
  },
};

onBeforeCreateStream(async (track) => {
  return null; // Let the registered extractors (YoutubeiExtractor) handle it natively
});

function canSendGuildMessage(guildId, messageKey, cooldownMs) {
  const key = `${guildId}:${messageKey}`;
  const now = Date.now();
  const nextAllowedAt = guildMessageCooldowns.get(key) || 0;

  if (now < nextAllowedAt) return false;

  guildMessageCooldowns.set(key, now + cooldownMs);
  return true;
}

function truncate(text, maxLength) {
  if (!text || typeof text !== 'string') return '';
  return text.length > maxLength ? `${text.slice(0, maxLength - 1)}...` : text;
}

function formatDurationMs(ms) {
  const numeric = Number(ms);
  if (!Number.isFinite(numeric) || numeric <= 0) return '0:00';

  const totalSeconds = Math.floor(numeric / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }

  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function parseTimeToMs(input) {
  if (!input) return null;

  const raw = String(input).trim().toLowerCase();
  if (!raw) return null;

  if (/^\d+$/.test(raw)) {
    return Number(raw) * 1000;
  }

  const unitMatch = raw.match(/^(\d+)(s|m|h)$/);
  if (unitMatch) {
    const value = Number(unitMatch[1]);
    const unit = unitMatch[2];
    if (unit === 's') return value * 1000;
    if (unit === 'm') return value * 60 * 1000;
    if (unit === 'h') return value * 60 * 60 * 1000;
  }

  const parts = raw.split(':').map((x) => x.trim());
  if (parts.some((p) => !/^\d+$/.test(p))) return null;

  if (parts.length === 2) {
    const minutes = Number(parts[0]);
    const seconds = Number(parts[1]);
    if (seconds >= 60) return null;
    return (minutes * 60 + seconds) * 1000;
  }

  if (parts.length === 3) {
    const hours = Number(parts[0]);
    const minutes = Number(parts[1]);
    const seconds = Number(parts[2]);
    if (minutes >= 60 || seconds >= 60) return null;
    return (hours * 3600 + minutes * 60 + seconds) * 1000;
  }

  return null;
}

function renderProgressBar(progress, size = 15) {
  const safeProgress = Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : 0;
  const filled = Math.round((safeProgress / 100) * size);
  const empty = size - filled;
  return `${'━'.repeat(filled)}🔘${'━'.repeat(empty)}`;
}

function getPlatformConfig(platform) {
  return PLATFORM_CONFIG[platform] || PLATFORM_CONFIG.auto;
}

function inferPlatformFromHostname(hostname) {
  const host = String(hostname || '').toLowerCase();
  if (!host) return null;

  if (host.includes('youtube.com') || host.includes('youtu.be')) return 'youtube';
  if (host.includes('soundcloud.com')) return 'soundcloud';
  if (host.includes('spotify.com')) return 'spotify';
  if (host.includes('apple.com') || host.includes('itunes.apple.com')) return 'applemusic';
  if (host.includes('deezer.com')) return 'deezer';
  if (host.includes('tidal.com')) return 'tidal';
  return null;
}

function getQueryTypeForPlatformUrl(platform) {
  if (platform === 'youtube') return QueryType.YOUTUBE_VIDEO;
  if (platform === 'soundcloud') return QueryType.SOUNDCLOUD_TRACK;
  if (platform === 'spotify') return QueryType.SPOTIFY_SONG;
  if (platform === 'applemusic') return QueryType.APPLE_MUSIC_SONG;
  return null;
}

function normalizeQueryInput(query) {
  const rawQuery = String(query || '').trim();
  if (!rawQuery) {
    return {
      rawQuery: '',
      normalizedQuery: '',
      looksLikeUrl: false,
      hostname: '',
      detectedPlatform: null,
    };
  }

  let normalizedQuery = rawQuery;
  let parsedUrl = null;

  try {
    normalizedQuery = rawQuery.startsWith('www.') ? `https://${rawQuery}` : rawQuery;
    parsedUrl = new URL(normalizedQuery);
  } catch {
    parsedUrl = null;
  }

  const looksLikeUrl = parsedUrl != null || /^https?:\/\//i.test(rawQuery);
  const hostname = parsedUrl?.hostname?.toLowerCase() || '';
  const detectedPlatform = inferPlatformFromHostname(hostname);

  return {
    rawQuery,
    normalizedQuery,
    looksLikeUrl,
    hostname,
    detectedPlatform,
  };
}

function normalizeForMatch(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/\[[^\]]*]/g, ' ')
    .replace(/\([^)]*\)/g, ' ')
    .replace(/[^a-z0-9\s]/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function tokenizeForMatch(value) {
  return normalizeForMatch(value)
    .split(' ')
    .map((token) => token.trim())
    .filter((token) => token.length > 1);
}

function cleanExternalTitle(value) {
  const title = String(value || '')
    .replace(/\s+/g, ' ')
    .trim();

  if (!title) return '';

  return title
    .replace(/\s*[\-|•|·]\s*(youtube|youtube music|spotify|apple music|deezer|tidal)\s*$/i, '')
    .replace(/\s*\|\s*(watch|listen).*$/i, '')
    .replace(/\s*-\s*(official|lyrics?|music video|video)\s*$/i, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function extractTitleFromHtml(html) {
  const source = String(html || '');
  if (!source) return '';

  const ogMatch = source.match(/<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']/i);
  if (ogMatch?.[1]) return cleanExternalTitle(ogMatch[1]);

  const titleMatch = source.match(/<title[^>]*>([^<]+)<\/title>/i);
  if (titleMatch?.[1]) return cleanExternalTitle(titleMatch[1]);

  return '';
}

async function fetchTrackTitleFromPage(url) {
  if (typeof fetch !== 'function') return '';

  try {
    const response = await fetch(url, {
      method: 'GET',
      redirect: 'follow',
      headers: {
        'User-Agent':
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
      },
      signal: AbortSignal.timeout(7_000),
    });

    if (!response.ok) return '';
    const html = await response.text();
    return extractTitleFromHtml(html);
  } catch {
    return '';
  }
}

async function prepareSearchInput(query, platform) {
  const normalized = normalizeQueryInput(query);
  const selectedPlatform = PLATFORM_CONFIG[platform] ? platform : 'auto';

  if (!normalized.looksLikeUrl) {
    return {
      query: normalized.rawQuery,
      selectedPlatform,
      fallbackQuery: normalized.rawQuery,
      detectedPlatform: normalized.detectedPlatform,
    };
  }

  const detected = normalized.detectedPlatform;
  const shouldFetchTitle = detected === 'deezer' || detected === 'tidal';

  if (shouldFetchTitle) {
    const extractedTitle = await fetchTrackTitleFromPage(normalized.normalizedQuery);
    if (extractedTitle) {
      return {
        query: extractedTitle,
        selectedPlatform: 'auto',
        fallbackQuery: extractedTitle,
        detectedPlatform: detected,
      };
    }
  }

  return {
    query: normalized.normalizedQuery,
    selectedPlatform,
    fallbackQuery: normalized.rawQuery,
    detectedPlatform: detected,
  };
}

function uniqueQueryTypes(queryTypes) {
  const unique = [];
  for (const type of queryTypes) {
    if (!type || unique.includes(type)) continue;
    unique.push(type);
  }
  return unique;
}

function buildSearchEngineCandidates(platform, resolvedType, looksLikeUrl, detectedPlatform) {
  const youtubePriorityEngine = isYoutubeiReady ? YOUTUBEI_SEARCH_ENGINE : QueryType.YOUTUBE_SEARCH;

  if (looksLikeUrl) {
    const urlSpecific = [
      QueryType.YOUTUBE_VIDEO,
      QueryType.YOUTUBE_PLAYLIST,
      QueryType.SOUNDCLOUD_TRACK,
      QueryType.SOUNDCLOUD_PLAYLIST,
      QueryType.SPOTIFY_SONG,
      QueryType.SPOTIFY_ALBUM,
      QueryType.SPOTIFY_PLAYLIST,
      QueryType.APPLE_MUSIC_SONG,
      QueryType.APPLE_MUSIC_ALBUM,
      QueryType.APPLE_MUSIC_PLAYLIST,
    ];

    if (detectedPlatform === 'youtube') {
      return uniqueQueryTypes([youtubePriorityEngine, resolvedType, QueryType.AUTO_SEARCH, QueryType.SOUNDCLOUD_SEARCH]);
    }

    if (urlSpecific.includes(resolvedType)) {
      return uniqueQueryTypes([resolvedType, QueryType.AUTO_SEARCH, youtubePriorityEngine, QueryType.SOUNDCLOUD_SEARCH]);
    }

    return uniqueQueryTypes([resolvedType, QueryType.AUTO_SEARCH, youtubePriorityEngine, QueryType.SOUNDCLOUD_SEARCH]);
  }

  if (platform === 'youtube') {
    return uniqueQueryTypes([youtubePriorityEngine, QueryType.AUTO_SEARCH, QueryType.SOUNDCLOUD_SEARCH]);
  }

  if (platform === 'youtubemusic') {
    return uniqueQueryTypes([youtubePriorityEngine, QueryType.AUTO_SEARCH]);
  }

  if (platform === 'soundcloud') {
    return uniqueQueryTypes([QueryType.SOUNDCLOUD_SEARCH, youtubePriorityEngine, QueryType.AUTO_SEARCH]);
  }

  if (platform === 'spotify') {
    return uniqueQueryTypes([QueryType.SPOTIFY_SEARCH, youtubePriorityEngine, QueryType.AUTO_SEARCH]);
  }

  if (platform === 'applemusic') {
    return uniqueQueryTypes([QueryType.APPLE_MUSIC_SEARCH, youtubePriorityEngine, QueryType.AUTO_SEARCH]);
  }

  if (platform === 'deezer' || platform === 'tidal') {
    return uniqueQueryTypes([QueryType.AUTO_SEARCH, youtubePriorityEngine, QueryType.SOUNDCLOUD_SEARCH]);
  }

  if (platform === 'auto') {
    return uniqueQueryTypes([QueryType.SOUNDCLOUD_SEARCH, youtubePriorityEngine, QueryType.AUTO_SEARCH]);
  }

  return uniqueQueryTypes([youtubePriorityEngine, QueryType.AUTO_SEARCH, QueryType.SOUNDCLOUD_SEARCH]);
}

function resolveSearchOptions(query, platform) {
  const selectedPlatform = PLATFORM_CONFIG[platform] ? platform : 'auto';
  const config = getPlatformConfig(selectedPlatform);
  const normalized = normalizeQueryInput(query);

  const preparedQuery = normalized.looksLikeUrl ? normalized.normalizedQuery : config.decorateQuery(normalized.rawQuery);
  const resolved = QueryResolver.resolve(preparedQuery, config.searchEngine || QueryType.AUTO_SEARCH);

  let resolvedType = resolved?.type || config.searchEngine || QueryType.AUTO_SEARCH;
  if (normalized.looksLikeUrl && [QueryType.AUTO, QueryType.AUTO_SEARCH].includes(resolvedType)) {
    const inferredType = getQueryTypeForPlatformUrl(normalized.detectedPlatform);
    if (inferredType) {
      resolvedType = inferredType;
    }
  }

  const searchEngines = buildSearchEngineCandidates(
    selectedPlatform,
    resolvedType,
    normalized.looksLikeUrl,
    normalized.detectedPlatform,
  );

  return {
    query: resolved?.query || preparedQuery,
    rawQuery: normalized.rawQuery,
    searchEngines,
    primarySearchEngine: searchEngines[0] || QueryType.AUTO_SEARCH,
    fallbackSearchEngine: QueryType.SOUNDCLOUD_SEARCH,
    label: config.label,
    looksLikeUrl: normalized.looksLikeUrl,
    detectedPlatform: normalized.detectedPlatform,
    resolvedType,
    selectedPlatform,
  };
}

function getSourceLabel(track) {
  const source = String(track?.source || 'arbitrary').toLowerCase();
  const label = SOURCE_LABELS[source] || String(track?.source || 'Unknown');
  const emoji = getEmojiToken(PLATFORM_EMOJIS[source], FALLBACK_PLATFORM_EMOJIS[source] || '🎶');
  return `${emoji} ${label}`;
}

function getEmojiToken(configuredEmoji, fallback) {
  const value = String(configuredEmoji || '').trim();
  if (value.startsWith('<') && value.endsWith('>')) return value;
  return value || fallback;
}

function getButtonEmoji(configuredEmoji, fallback) {
  const token = String(configuredEmoji || '').trim();
  const match = token.match(/^<(a?):([A-Za-z0-9_]{2,32}):(\d{17,20})>$/);
  if (match) {
    return { name: match[2], id: match[3], animated: match[1] === 'a' };
  }
  return token || fallback;
}

function shouldThrottlePlayCommand(guildId, userId, cooldownMs = 2_000) {
  if (!guildId || !userId) return false;

  const key = `${guildId}:${userId}`;
  const now = Date.now();
  const nextAllowedAt = playCommandCooldowns.get(key) || 0;

  if (now < nextAllowedAt) {
    return true;
  }

  playCommandCooldowns.set(key, now + cooldownMs);
  return false;
}

function scoreTrackAgainstQuery(track, rawQuery, strictMode = false) {
  const query = normalizeForMatch(rawQuery);
  if (!query) return 0;

  const queryTokens = tokenizeForMatch(query);
  if (queryTokens.length === 0) return 0;

  const title = normalizeForMatch(track?.cleanTitle || track?.title || '');
  const author = normalizeForMatch(track?.author || '');
  const combined = `${title} ${author}`.trim();
  if (!combined) return 0;

  let score = 0;
  const matchCount = queryTokens.filter((token) => combined.includes(token)).length;
  score += (matchCount / queryTokens.length) * 100;

  if (strictMode && title === query) score += 200;
  if (strictMode && title.startsWith(`${query} `)) score += 80;
  if (strictMode && title.includes(` ${query} `)) score += 40;

  if (title.startsWith(query)) score += 20;
  if (title.includes(query)) score += 10;

  const queryHasRemix = /\b(remix|slowed|reverb|lofi|mashup|cover|lyrics?)\b/i.test(rawQuery);
  const titleHasRemix = /\b(remix|slowed|reverb|lofi|mashup|cover|lyrics?)\b/i.test(title);
  if (titleHasRemix && !queryHasRemix) score -= 20;

  const queryHasMovie = /\b(movie|full|part)\b/i.test(rawQuery);
  const titleLooksMovie = /\b(full movie|part \d+\/\d+)\b/i.test(title);
  if (titleLooksMovie && !queryHasMovie) score -= 30;

  if (strictMode && matchCount < Math.max(2, Math.floor(queryTokens.length * 0.6))) {
    score -= 70;
  }

  return score;
}

const NON_OFFICIAL_VARIANTS = [
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
function canonicalSongKey(track) {
  const title = String(track?.cleanTitle || track?.title || '')
    .replace(/\b(official\s*(audio|video|music video)|audio|music video|vevo|topic|hd|4k|lyrics?)\b/gi, ' ')
    .replace(/\([^)]*\)|\[[^\]]*\]/g, ' ')
    .replace(/\b(feat\.?|ft\.?)\b.*$/i, ' ');
  const normalizedTitle = normalizeForMatch(title);
  // Uploaders differ between mirror channels, but the normalized catalog title
  // remains stable enough to stop cross-source autoplay repeats.
  return normalizedTitle ? normalizedTitle.replace(/\s+/g, ' ').trim() : '';
}

function isUnrequestedVariant(track, rawQuery = '') {
  const query = String(rawQuery || '');
  if (isLikelyUrl(query)) return false;
  const title = String(track?.cleanTitle || track?.title || '');
  const url = String(track?.url || '');
  const durationMs = Number(track?.durationMS || 0);
  if (NON_OFFICIAL_VARIANTS.some((pattern) => pattern.test(title) && !pattern.test(query)) || /\/shorts?\//i.test(url)) return true;
  if (durationMs > 0 && durationMs < 60_000) return true;
  return false;
}

function prioritizeTracksForPlayback(tracks, rawQuery = '', strictMode = false) {
  if (!Array.isArray(tracks)) return tracks;

  const sourceScore = {
    soundcloud: 6,
    youtube: 4,
    arbitrary: 3,
    spotify: 2,
    apple_music: 2,
  };

  const unique = new Map();
  for (const track of tracks) {
    if (!track?.url || isUnrequestedVariant(track, rawQuery)) continue;
    const key = canonicalSongKey(track) || String(track.url);
    const old = unique.get(key);
    const officialSignal = /\b(official|vevo|topic|provided to youtube)\b/i.test(`${track.title} ${track.author} ${track.url}`) ? 18 : 0;
    const quality = scoreTrackAgainstQuery(track, rawQuery, strictMode) + (sourceScore[track?.source] ?? 1) + officialSignal;
    if (!old || quality > old.quality) unique.set(key, { track, quality });
  }
  return [...unique.values()].sort((a, b) => {
    const aScore = a.quality;
    const bScore = b.quality;
    return bScore - aScore;
  }).map(({ track }) => track);
}

function ensureFavoritesStore() {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
  }

  if (!fs.existsSync(FAVORITES_PATH)) {
    fs.writeFileSync(FAVORITES_PATH, '{}\n', 'utf8');
  }
}

function readFavoritesStore() {
  ensureFavoritesStore();

  try {
    const raw = fs.readFileSync(FAVORITES_PATH, 'utf8');
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeFavoritesStore(store) {
  ensureFavoritesStore();
  fs.writeFileSync(FAVORITES_PATH, `${JSON.stringify(store, null, 2)}\n`, 'utf8');
}

function getUserFavorites(userId) {
  const store = readFavoritesStore();
  const favorites = store[userId];
  return Array.isArray(favorites) ? favorites : [];
}

function normalizeFavoriteTrack(track) {
  return {
    title: truncate(track.cleanTitle || track.title || 'Unknown Track', 120),
    author: truncate(track.author || '', 100),
    url: track.url || '',
    duration: track.duration || formatDurationMs(track.durationMS),
    source: String(track.source || 'arbitrary'),
    addedAt: Date.now(),
  };
}

function saveTrackToFavorites(userId, track) {
  const store = readFavoritesStore();
  const favorites = Array.isArray(store[userId]) ? store[userId] : [];
  const normalized = normalizeFavoriteTrack(track);

  const exists = favorites.some((entry) => {
    if (normalized.url && entry.url) return entry.url === normalized.url;
    return entry.title === normalized.title;
  });

  if (exists) {
    return { added: false, total: favorites.length, track: normalized };
  }

  favorites.push(normalized);
  store[userId] = favorites;
  writeFavoritesStore(store);

  return { added: true, total: favorites.length, track: normalized };
}

function removeFavoriteByIndex(userId, index1Based) {
  const store = readFavoritesStore();
  const favorites = Array.isArray(store[userId]) ? store[userId] : [];
  const index = index1Based - 1;

  if (index < 0 || index >= favorites.length) {
    return { removed: null, total: favorites.length };
  }

  const [removed] = favorites.splice(index, 1);
  store[userId] = favorites;
  writeFavoritesStore(store);

  return { removed, total: favorites.length };
}

function clearFavorites(userId) {
  const store = readFavoritesStore();
  const count = Array.isArray(store[userId]) ? store[userId].length : 0;
  store[userId] = [];
  writeFavoritesStore(store);
  return count;
}

function getBotVoicePermissions(voiceChannel, guild) {
  const me = guild.members.me;
  if (!me) {
    return {
      ok: false,
      message: 'I cannot resolve my bot member in this server yet. Please try again.',
    };
  }

  const perms = voiceChannel.permissionsFor(me);
  if (!perms || !perms.has(PermissionFlagsBits.Connect)) {
    return { ok: false, message: 'I need the Connect permission in your voice channel.' };
  }

  if (!perms.has(PermissionFlagsBits.Speak)) {
    return { ok: false, message: 'I need the Speak permission in your voice channel.' };
  }

  return { ok: true, message: '' };
}

function getQueue(guildId) {
  return player.nodes.get(guildId);
}

function disableContinuousPlayback(guildId, queue) {
  twentyFourSevenGuilds.delete(guildId);
  radioStationsByGuild.delete(guildId);
  if (queue?.metadata) delete queue.metadata.radioStationId;
  if (queue?.repeatMode !== undefined && queue.repeatMode !== QueueRepeatMode.OFF) {
    queue.setRepeatMode(QueueRepeatMode.OFF);
  }
}

function hasActiveTrack(queue) {
  return Boolean(queue && queue.currentTrack);
}

function buildControlsRow(queue) {
  const isPaused = queue?.node?.isPaused?.();
  return new ActionRowBuilder().addComponents(
    new ButtonBuilder()
      .setCustomId(BUTTON_IDS.PAUSE_RESUME)
      .setStyle(isPaused ? ButtonStyle.Primary : ButtonStyle.Success)
      .setEmoji(getButtonEmoji(isPaused ? EMOJIS.play : EMOJIS.pause, isPaused ? '▶️' : '⏸️')),
    new ButtonBuilder()
      .setCustomId(BUTTON_IDS.PREVIOUS)
      .setStyle(ButtonStyle.Primary)
      .setEmoji(getButtonEmoji(EMOJIS.previous, '⏮️')),
    new ButtonBuilder()
      .setCustomId(BUTTON_IDS.SKIP)
      .setStyle(ButtonStyle.Primary)
      .setEmoji(getButtonEmoji(EMOJIS.skip, '⏭️')),
    new ButtonBuilder()
      .setCustomId(BUTTON_IDS.STOP)
      .setStyle(ButtonStyle.Danger)
      .setEmoji(getButtonEmoji(EMOJIS.stop, '⏹️')),
    new ButtonBuilder()
      .setCustomId(BUTTON_IDS.QUEUE)
      .setStyle(ButtonStyle.Secondary)
      .setEmoji(getButtonEmoji(EMOJIS.queue, '📜')),
  );
}

function buildLibraryControlsRow() {
  return new ActionRowBuilder().addComponents(
    new ButtonBuilder()
      .setCustomId(BUTTON_IDS.LIKE)
      .setStyle(ButtonStyle.Secondary)
      .setEmoji(getButtonEmoji(EMOJIS.heart, '💖'))
      .setLabel('Favorite'),
    new ButtonBuilder()
      .setCustomId(BUTTON_IDS.PLAYLIST)
      .setStyle(ButtonStyle.Secondary)
      .setEmoji(getButtonEmoji(EMOJIS.playlist, '📑'))
      .setLabel('My Playlist'),
  );
}

function buildNowPlayingCard(queue, track) {
  const current = track || queue?.currentTrack;
  if (!current) {
    return new ContainerBuilder().setAccentColor(BRAND_COLOR)
      .addTextDisplayComponents(new TextDisplayBuilder().setContent(`### ${BRAND_NAME}\nNothing is currently playing.`));
  }

  const timestamp = queue?.node?.getTimestamp?.();
  const progressLine = timestamp
    ? `${timestamp.current.label} ${renderProgressBar(timestamp.progress)} ${timestamp.total.label}`
    : `${formatDurationMs(queue?.node?.playbackTime || 0)} ━━━━━━━━🔘━━━━━━━━ ${current.live ? 'LIVE' : (current.duration || formatDurationMs(current.durationMS))}`;
  const requestedBy = current.requestedBy ? `<@${current.requestedBy.id}>` : 'Unknown';
  const title = truncate(current.cleanTitle || current.title || 'Unknown Track', 80);
  const linkedTitle = current.url ? `[${title}](${current.url})` : title;
  const author = truncate(current.author || 'Unknown artist', 50);
  const duration = current.live ? 'LIVE' : (current.duration || formatDurationMs(current.durationMS));
  const source = getSourceLabel(current);
  const station = queue?.metadata?.radioStationId ? `  •  ${RADIO_STATIONS[queue.metadata.radioStationId]?.genre || 'Radio'}` : '';

  const nextTrack = queue?.tracks?.toArray?.()?.[0];
  let upNextText = 'End of queue (Add tracks with `/play`)';
  if (nextTrack) {
    const nextTitle = truncate(nextTrack.cleanTitle || nextTrack.title || 'Unknown', 40);
    const nextAuthor = truncate(nextTrack.author || 'Unknown', 25);
    const nextDuration = nextTrack.live ? 'LIVE' : (nextTrack.duration || formatDurationMs(nextTrack.durationMS));
    upNextText = `**${nextTitle}** by **${nextAuthor}** [${nextDuration}]`;
  } else if (queue?.repeatMode === QueueRepeatMode.AUTOPLAY || twentyFourSevenGuilds.has(queue?.guild?.id)) {
    upNextText = `${EMOJIS.radio} **Smart Autoplay / Continuous Radio**`;
  }

  const section = new SectionBuilder()
    .addTextDisplayComponents(
      new TextDisplayBuilder().setContent(
        `### ${EMOJIS.play} Now Playing\n` +
        `**${linkedTitle}** by **${author}** [${duration}]\n\n` +
        `\`${progressLine}\``
      )
    );

  const thumbUrl = (current.thumbnail && /^https:\/\//i.test(current.thumbnail))
    ? current.thumbnail
    : BRAND_LOGO_URL;
  section.setThumbnailAccessory(new ThumbnailBuilder().setURL(thumbUrl).setDescription(`${title} artwork`));

  return new ContainerBuilder().setAccentColor(BRAND_COLOR)
    .addSectionComponents(section)
    .addSeparatorComponents(new SeparatorBuilder().setDivider(true).setSpacing(SeparatorSpacingSize.Small))
    .addActionRowComponents(buildControlsRow(queue))
    .addActionRowComponents(buildLibraryControlsRow())
    .addSeparatorComponents(new SeparatorBuilder().setDivider(true).setSpacing(SeparatorSpacingSize.Small))
    .addTextDisplayComponents(
      new TextDisplayBuilder().setContent(
        `Track requested by ${requestedBy}  •  ${source}${station}\n` +
        `⏭️ **Up Next:** ${upNextText}`
      )
    );
}

function buildNowPlayingEmbed(queue, track) {
  const current = track || queue?.currentTrack;
  if (!current) {
    return createNotificationEmbed(`${EMOJIS.syncink} ${BRAND_NAME}`, 'Nothing is currently playing.');
  }

  const timestamp = queue?.node?.getTimestamp?.();
  const progressLine = timestamp
    ? `${timestamp.current.label} ${renderProgressBar(timestamp.progress)} ${timestamp.total.label}`
    : `${formatDurationMs(queue?.node?.playbackTime || 0)} ━━━━━━━━🔘━━━━━━━━ ${current.live ? 'LIVE' : (current.duration || formatDurationMs(current.durationMS))}`;
  const requestedBy = current.requestedBy ? `<@${current.requestedBy.id}>` : 'Unknown';
  const title = truncate(current.cleanTitle || current.title || 'Unknown Track', 80);
  const linkedTitle = current.url ? `[${title}](${current.url})` : title;
  const author = truncate(current.author || 'Unknown artist', 60);
  const duration = current.live ? 'LIVE' : (current.duration || formatDurationMs(current.durationMS));
  const source = getSourceLabel(current);
  const station = queue?.metadata?.radioStationId ? `  •  ${RADIO_STATIONS[queue.metadata.radioStationId]?.genre || 'Radio'}` : '';

  const nextTrack = queue?.tracks?.toArray?.()?.[0];
  let upNextText = 'End of queue';
  if (nextTrack) {
    const nextTitle = truncate(nextTrack.cleanTitle || nextTrack.title || 'Unknown', 40);
    const nextAuthor = truncate(nextTrack.author || 'Unknown', 25);
    const nextDuration = nextTrack.live ? 'LIVE' : (nextTrack.duration || formatDurationMs(nextTrack.durationMS));
    upNextText = `**[${nextTitle}](${nextTrack.url || 'https://discord.com'})** by **${nextAuthor}** [${nextDuration}]`;
  } else if (queue?.repeatMode === QueueRepeatMode.AUTOPLAY || twentyFourSevenGuilds.has(queue?.guild?.id)) {
    upNextText = `${EMOJIS.radio} **Smart Autoplay / Continuous Radio**`;
  }

  const embed = new EmbedBuilder()
    .setColor(BRAND_COLOR)
    .setAuthor({ name: `${BRAND_NAME} • Now Playing`, iconURL: BRAND_LOGO_URL })
    .setTitle(`${truncate(title, 80)}`)
    .setURL(current.url || 'https://discord.com')
    .setDescription(
      `**${linkedTitle}**\n` +
      `${EMOJIS.syncinkmusic} **Artist:** ${author} [${duration}]\n\n` +
      `${EMOJIS.time} \`${progressLine}\`\n\n` +
      `${EMOJIS.members} **Requested by:** ${requestedBy} • ${source}${station}\n` +
      `⏭️ **Up Next:** ${upNextText}`
    )
    .setFooter({ text: `${BRAND_NAME} • Pure Audio Experience`, iconURL: BRAND_LOGO_URL })
    .setTimestamp();

  const thumbUrl = (current.thumbnail && /^https:\/\//i.test(current.thumbnail)) ? current.thumbnail : BRAND_LOGO_URL;
  embed.setThumbnail(thumbUrl);

  return embed;
}

function buildNowPlayingPayload(queue, track) {
  try {
    return {
      components: [buildNowPlayingCard(queue, track)],
      flags: MessageFlags.IsComponentsV2,
    };
  } catch (err) {
    return {
      embeds: [buildNowPlayingEmbed(queue, track)],
      components: [buildControlsRow(queue), buildLibraryControlsRow()],
    };
  }
}

async function sendOrEditNowPlaying(target, queue, track) {
  const payload = buildNowPlayingPayload(queue, track);
  let message = null;
  try {
    if (typeof target.editReply === 'function') {
      message = await target.editReply(payload);
    } else if (typeof target.edit === 'function') {
      message = await target.edit(payload);
    } else if (typeof target.send === 'function') {
      message = await target.send(payload);
    }
  } catch {
    const fallback = {
      embeds: [buildNowPlayingEmbed(queue, track)],
      components: [buildControlsRow(queue), buildLibraryControlsRow()],
    };
    if (typeof target.editReply === 'function') {
      message = await target.editReply(fallback).catch(() => null);
    } else if (typeof target.edit === 'function') {
      message = await target.edit(fallback).catch(() => null);
    } else if (typeof target.send === 'function') {
      message = await target.send(fallback).catch(() => null);
    }
  }
  if (message && queue?.guild?.id) {
    setNowPlayingRegistry(queue, message);
  }
  return message;
}

function buildQueueEmbed(queue) {
  const current = queue.currentTrack;
  const upcoming = queue.tracks.toArray().slice(0, MAX_QUEUE_PREVIEW);

  const embed = new EmbedBuilder()
    .setColor(BRAND_COLOR)
    .setAuthor({ name: BRAND_NAME, iconURL: BRAND_LOGO_URL })
    .setTitle(`${EMOJIS.queue} Music Queue`)
    .setFooter({ text: `${BRAND_NAME} • ${queue.size} track(s) waiting • Volume: ${queue.node.volume}%`, iconURL: BRAND_LOGO_URL })
    .setTimestamp();

  let desc = '';
  if (current) {
    const currentDuration = current.live ? 'LIVE' : current.duration || formatDurationMs(current.durationMS);
    const linkedTitle = current.url ? `[${current.title}](${current.url})` : current.title;
    desc += `▶ **Now Playing:**\n${linkedTitle}\n${EMOJIS.time} \`${currentDuration}\`  •  ${EMOJIS.syncinkmusic} ${current.author || 'Unknown'}\n\n`;
  } else {
    desc += `${EMOJIS.warning} Queue is currently empty.\n\n`;
  }

  embed.setDescription(desc);

  if (upcoming.length > 0) {
    const lines = upcoming.map((item, index) => {
      const title = truncate(item.cleanTitle || item.title || 'Unknown Track', 60);
      const duration = item.live ? 'LIVE' : item.duration || formatDurationMs(item.durationMS);
      const linkedTitle = item.url ? `[${title}](${item.url})` : title;
      return `**${index + 1}.** ${linkedTitle}  •  \`${duration}\`  •  *${item.author || 'Artist'}*`;
    });

    embed.addFields({
      name: `${EMOJIS.syncinkmusic} Up Next (${queue.size} total)`,
      value: lines.join('\n'),
      inline: false,
    });
  }

  return embed;
}

function buildSearchEmbed(query, platform, results) {
  const config = getPlatformConfig(platform);
  const platformEmoji = EMOJIS[platform] || EMOJIS.syncinkmusic;

  const embed = new EmbedBuilder()
    .setColor(BRAND_COLOR)
    .setAuthor({ name: BRAND_NAME, iconURL: BRAND_LOGO_URL })
    .setTitle(`${EMOJIS.looking} Search Results`)
    .setDescription(`Query: **${truncate(query, 80)}**  •  Platform: ${platformEmoji} **${config.label}**`)
    .setFooter({ text: `${BRAND_NAME} • Choose a track number below or click Cancel`, iconURL: BRAND_LOGO_URL })
    .setTimestamp();

  if (!results.length) {
    embed.setDescription(`${EMOJIS.refused} No tracks found for: **${truncate(query, 80)}**`);
    return embed;
  }

  const lines = results.slice(0, 10).map((track, index) => {
    const title = truncate(track.cleanTitle || track.title || 'Unknown Track', 65);
    const author = truncate(track.author || 'Unknown Artist', 40);
    const duration = track.live ? 'LIVE' : track.duration || formatDurationMs(track.durationMS);
    const linkedTitle = track.url ? `[${title}](${track.url})` : title;
    return `**${index + 1}. ${linkedTitle}**\n${EMOJIS.time} Duration: \`${duration}\`  •  ${EMOJIS.syncinkmusic} Author: **${author}**`;
  });

  embed.addFields({
    name: 'Top Results',
    value: lines.join('\n\n'),
    inline: false,
  });

  return embed;
}

function buildSearchResultRows(sessionId, results) {
  const tracks = results.slice(0, 10);
  const rows = [];

  const row1 = new ActionRowBuilder();
  for (let index = 0; index < Math.min(5, tracks.length); index += 1) {
    row1.addComponents(
      new ButtonBuilder()
        .setCustomId(`syncink_search_pick:${sessionId}:${index}`)
        .setStyle(ButtonStyle.Primary)
        .setLabel(String(index + 1))
        .setEmoji(getButtonEmoji(EMOJIS.approved, '▶️'))
    );
  }
  rows.push(row1);

  if (tracks.length > 5) {
    const row2 = new ActionRowBuilder();
    for (let index = 5; index < tracks.length; index += 1) {
      row2.addComponents(
        new ButtonBuilder()
          .setCustomId(`syncink_search_pick:${sessionId}:${index}`)
          .setStyle(ButtonStyle.Primary)
          .setLabel(String(index + 1))
          .setEmoji(getButtonEmoji(EMOJIS.approved, '▶️'))
      );
    }
    rows.push(row2);
  }

  const cancelRow = new ActionRowBuilder().addComponents(
    new ButtonBuilder()
      .setCustomId(`syncink_search_cancel:${sessionId}`)
      .setStyle(ButtonStyle.Danger)
      .setLabel('Cancel')
      .setEmoji(getButtonEmoji(EMOJIS.refused, '❌'))
  );
  rows.push(cancelRow);

  return rows;
}

function buildLyricsEmbed(query, result) {
  const text = result?.plainLyrics || 'No lyrics found.';
  const preview = truncate(text, 3800);

  return new EmbedBuilder()
    .setColor(BRAND_COLOR)
    .setAuthor({ name: BRAND_NAME, iconURL: BRAND_LOGO_URL })
    .setTitle(`${EMOJIS.syncinkmusic} Lyrics: ${truncate(query, 70)}`)
    .setDescription(`**${truncate(query, 160)}**\n\n${preview}`)
    .setFooter({ text: result ? `${result.trackName || ''} ${result.artistName ? `- ${result.artistName}` : ''}`.trim() : BRAND_NAME, iconURL: BRAND_LOGO_URL })
    .setTimestamp();
}

function buildHelpEmbed() {
  return new EmbedBuilder()
    .setColor(BRAND_COLOR)
    .setAuthor({ name: BRAND_NAME, iconURL: BRAND_LOGO_URL })
    .setTitle(`${EMOJIS.syncink} ${BRAND_NAME} • Command Guide`)
    .setDescription('High-fidelity Discord radio & music playback system.')
    .addFields(
      {
        name: `${EMOJIS.radio} Radio & 24/7 Live`,
        value: '`/radio station:<choice>` • Tune into 24/7 genre stations\n`/lofi` • Continuous relaxing study beats\n`/247 mode:<on/off>` • Never leaves voice channel',
      },
      {
        name: `${EMOJIS.play} Playback Controls`,
        value: '`/play <query>` • Search & play music instantly\n`/search <query>` • Interactive 10-result picker\n`/pause` • `/resume` • `/skip` • `/stop` • `/replay` • `/seek`\n`/np` • Beautiful interactive music control card',
      },
      {
        name: `${EMOJIS.queue} Queue & Playlist Management`,
        value: '`/queue list` • View full upcoming tracks\n`/queue clear` • Empty upcoming queue\n`/shuffle` • Randomize playback order\n`/loop <mode>` • Repeat current track or queue\n`/volume <percent>` • Adjust digital gain volume\n`/autoplay <mode>` • Endless smart song recommendation\n`/playlist show|play|clear|remove` • Custom favorites',
      },
      {
        name: `${EMOJIS.syncvolume} Audio Effects & DSP Filters`,
        value: '`/filter type:<bassboost/8d/nightcore/vaporwave/karaoke/normalizer/off>`\n`/bassboost mode:<low/normal/high/off>`\n`/8d mode:<on/off>`\n`/lyrics <query>` • Display synchronized track lyrics',
      },
      {
        name: `${EMOJIS.spotify} ${EMOJIS.youtube} ${EMOJIS.apple} ${EMOJIS.soundcloud} ${EMOJIS.deezer} ${EMOJIS.tidal} Supported Platforms`,
        value: 'Spotify, YouTube, YouTube Music, Apple Music, SoundCloud, Deezer, TIDAL',
      },
    )
    .setFooter({ text: `${BRAND_NAME} • Pure Audio Experience`, iconURL: BRAND_LOGO_URL })
    .setTimestamp();
}

function buildFavoritesEmbed(user, favorites) {
  const top = favorites.slice(0, 10);
  const lines = top.map((track, index) => {
    const title = truncate(track.title || 'Unknown Track', 65);
    const duration = track.duration || 'Unknown';
    if (track.url) return `**${index + 1}.** [${title}](${track.url})  •  \`${duration}\``;
    return `**${index + 1}.** ${title}  •  \`${duration}\``;
  });

  return new EmbedBuilder()
    .setColor(BRAND_COLOR)
    .setAuthor({ name: BRAND_NAME, iconURL: BRAND_LOGO_URL })
    .setTitle(`${EMOJIS.heart} ${user.username}'s Favorites Playlist`)
    .setDescription(
      lines.length
        ? `${lines.join('\n')}\n\n${EMOJIS.play} Use \`/playlist play\` to queue this entire playlist!`
        : `No liked tracks yet. Click the **${EMOJIS.heart} Favorite** button while music plays to build your playlist.`
    )
    .setFooter({ text: `${BRAND_NAME} • Total Favorites: ${favorites.length}`, iconURL: BRAND_LOGO_URL })
    .setTimestamp();
}

async function safeReply(interaction, payload) {
  let finalPayload = payload;
  if (typeof payload === 'string') {
    finalPayload = { embeds: [createNotificationEmbed(`${EMOJIS.syncink} ${BRAND_NAME}`, payload)] };
  } else if (payload && payload.content && !payload.embeds && !payload.components) {
    const isError = /error|refused|fail|denied|cannot|not|invalid/i.test(payload.content);
    const color = isError ? ERROR_COLOR : BRAND_COLOR;
    const titleEmoji = isError ? EMOJIS.refused : EMOJIS.syncink;
    finalPayload = {
      embeds: [createNotificationEmbed(`${titleEmoji} ${BRAND_NAME}`, payload.content, color)],
      flags: payload.flags,
    };
  }
  if (interaction.deferred || interaction.replied) {
    return interaction.followUp(finalPayload).catch(() => null);
  }
  return interaction.reply(finalPayload).catch(() => null);
}

function createNotificationEmbed(title, description, color = BRAND_COLOR) {
  const embed = new EmbedBuilder()
    .setColor(color)
    .setAuthor({ name: BRAND_NAME, iconURL: BRAND_LOGO_URL })
    .setTitle(title)
    .setFooter({ text: `${BRAND_NAME} • Pure Audio Experience`, iconURL: BRAND_LOGO_URL })
    .setTimestamp();

  if (description) {
    embed.setDescription(description);
  }

  return embed;
}

async function safeReplyEmbed(interaction, title, description, color = BRAND_COLOR, ephemeral = false) {
  const embed = createNotificationEmbed(title, description, color);
  const payload = { embeds: [embed] };
  if (ephemeral) payload.flags = MessageFlags.Ephemeral;
  return safeReply(interaction, payload);
}

async function getInteractionVoiceChannel(interaction) {
  const member = await interaction.guild.members.fetch(interaction.user.id);
  return member.voice.channel || null;
}

async function ensureVoiceAndPermissions(interaction) {
  if (!interaction.inGuild()) {
    await safeReplyEmbed(interaction, `${EMOJIS.refused} Server Only`, 'This command can only be used in a Discord server.', ERROR_COLOR, true);
    return { ok: false, channel: null };
  }

  const voiceChannel = await getInteractionVoiceChannel(interaction);
  if (!voiceChannel) {
    await safeReplyEmbed(interaction, `${EMOJIS.warning} Voice Channel Required`, 'Please join a voice channel first, then try again.', ERROR_COLOR, true);
    return { ok: false, channel: null };
  }

  const permissionCheck = getBotVoicePermissions(voiceChannel, interaction.guild);
  if (!permissionCheck.ok) {
    await safeReplyEmbed(interaction, `${EMOJIS.refused} Missing Voice Permissions`, permissionCheck.message, ERROR_COLOR, true);
    return { ok: false, channel: null };
  }

  return { ok: true, channel: voiceChannel };
}

async function ensureSameVoiceChannel(interaction, queue) {
  const memberChannel = await getInteractionVoiceChannel(interaction);
  const queueChannel = queue?.channel;

  if (!memberChannel || !queueChannel || memberChannel.id !== queueChannel.id) {
    await safeReplyEmbed(
      interaction,
      `${EMOJIS.warning} Different Voice Channel`,
      'Join my current voice channel to use this playback control.',
      ERROR_COLOR,
      true
    );
    return false;
  }

  return true;
}

function buildBridgeSearchQuery(track) {
  if (!track) return null;

  const title = String(track.cleanTitle || track.title || '').trim();
  const author = String(track.author || '').trim();
  if (!title) return null;

  if (author) return `${title} ${author}`;
  return title;
}

function getGuildStrictMode(guildId) {
  if (!guildId) return STRICT_SONG_MODE_DEFAULT;
  if (!strictModeByGuild.has(guildId)) return STRICT_SONG_MODE_DEFAULT;
  return strictModeByGuild.get(guildId) === true;
}

function setGuildStrictMode(guildId, enabled) {
  if (!guildId) return;
  strictModeByGuild.set(guildId, enabled === true);
}

function resolveStrictMode(guildId, strictOverride) {
  if (typeof strictOverride === 'boolean') return strictOverride;
  return getGuildStrictMode(guildId);
}

function isStreamErrorRecoverable(error) {
  const message = String(error?.message || error || '').toLowerCase();
  if (!message) return false;

  return [
    'could not extract stream',
    'no stream',
    'sign in to confirm',
    'status code: 403',
    'unable to play this track',
    'failed to load stream',
    'private video',
    'video unavailable',
    'premature close',
    'aborted',
    'rate limit',
    'bot',
    'ip blocked',
  ].some((pattern) => message.includes(pattern)) || message.includes('stream') || message.includes('extract');
}

function shouldAttemptStreamRecovery(queue, track) {
  if (!queue?.guild?.id || !track) return false;

  const key = `${queue.guild.id}:${track.url || track.cleanTitle || track.title || 'unknown'}`;
  const now = Date.now();
  const nextAllowedAt = streamRecoveryCooldowns.get(key) || 0;
  if (now < nextAllowedAt) return false;

  streamRecoveryCooldowns.set(key, now + 120_000);
  return true;
}

async function recoverTrackFromStreamFailure(queue, track) {
  if (!queue?.channel || !track) return false;
  if (!shouldAttemptStreamRecovery(queue, track)) return false;

  const recoveryQuery = buildBridgeSearchQuery(track);
  if (!recoveryQuery) return false;

  const requestedBy = track.requestedBy || queue?.currentTrack?.requestedBy || null;
  const strictMode = getGuildStrictMode(queue.guild.id);
  const { result } = await searchWithFallbackEngines(recoveryQuery, 'soundcloud', requestedBy, { strictMode });
  const recoveredTrack = result?.tracks?.[0];
  if (!recoveredTrack) return false;

  const sameUrl = recoveredTrack.url && track.url && recoveredTrack.url === track.url;
  if (sameUrl) return false;

  queue.insertTrack(recoveredTrack, 0);
  // `skipOnNoStream` can advance while this async search is running. Only skip
  // if the failed track is still current; otherwise leave the replacement at
  // the head of the queue instead of skipping a healthy next track.
  const failedTrackIsCurrent = queue.currentTrack && (
    (track.url && queue.currentTrack.url === track.url) ||
    (track.id && queue.currentTrack.id === track.id)
  );
  if (!queue.isPlaying()) {
    queue.node.play();
  } else if (failedTrackIsCurrent) {
    queue.node.skip();
  }
  return true;
}

async function searchWithFallbackEngines(query, platform, requestedBy, options = {}) {
  const strictMode = options.strictMode === true;
  const resolved = resolveSearchOptions(query, platform);
  let lastError = null;

  for (const searchEngine of resolved.searchEngines) {
    if (searchEngine === YOUTUBEI_SEARCH_ENGINE && !isYoutubeiReady) {
      continue;
    }

    try {
      const result = await player.search(resolved.query, {
        requestedBy,
        searchEngine,
        fallbackSearchEngine: resolved.fallbackSearchEngine,
      });

      if (result?.hasTracks?.()) {
        const rankedTracks = prioritizeTracksForPlayback(result.tracks, resolved.rawQuery || resolved.query, strictMode);
        if (!rankedTracks.length) continue;
        result.setTracks(rankedTracks);
        return {
          result,
          usedEngine: searchEngine,
          resolved,
        };
      }

      if (process.env.PLAYER_DEBUG === 'true') {
        console.log(`[Search] Engine ${searchEngine} returned 0 tracks for query "${resolved.query}"`);
      }
    } catch (error) {
      lastError = error;
      if (process.env.PLAYER_DEBUG === 'true') {
        console.log(`[Search] Engine ${searchEngine} failed for "${resolved.query}": ${error?.message || error}`);
      }
    }
  }

  if (lastError) throw lastError;
  throw new Error(`No results found for "${resolved.query}"`);
}

async function runSearch(query, platform, requestedBy, options = {}) {
  const prepared = await prepareSearchInput(query, platform);
  const { result } = await searchWithFallbackEngines(prepared.query, prepared.selectedPlatform, requestedBy, options);
  return result;
}

async function queueAndPlay(voiceChannel, query, textChannel, requestedBy, platform = 'auto', options = {}) {
  const prepared = await prepareSearchInput(query, platform);
  const strictMode = options.strictMode === true;

  const baseOptions = {
    requestedBy,
    nodeOptions: createPlaybackNodeOptions({ textChannel }),
  };

  try {
    const { result: searchResult, usedEngine } = await searchWithFallbackEngines(
      prepared.query,
      prepared.selectedPlatform,
      requestedBy,
      { strictMode },
    );

    const result = await player.play(voiceChannel, searchResult, {
      ...baseOptions,
      searchEngine: usedEngine,
      fallbackSearchEngine: QueryType.SOUNDCLOUD_SEARCH,
    });

    if (DEFAULT_AUTOPLAY && result.queue.repeatMode === QueueRepeatMode.OFF) {
      result.queue.setRepeatMode(QueueRepeatMode.AUTOPLAY);
    }

    return result;
  } catch (primaryError) {
    const rawQuery = String(prepared.fallbackQuery || query || '').trim();
    const urlFallbackQuery = isLikelyUrl(rawQuery) ? await fetchTrackTitleFromPage(rawQuery) : '';
    const fallbackTextQuery = urlFallbackQuery || rawQuery;
    let bridgeQuery = null;

    // Bridge fallback: retry through YouTube search when metadata-source playback cannot stream.
    try {
      const bridgeSearch = await searchWithFallbackEngines(prepared.query, 'auto', requestedBy, { strictMode });
      const fallbackTrack = bridgeSearch.result.tracks[0];
      bridgeQuery = buildBridgeSearchQuery(fallbackTrack) || fallbackTextQuery;

      if (bridgeQuery) {
        const bridged = await searchWithFallbackEngines(bridgeQuery, 'youtube', requestedBy, { strictMode });
        const bridgedResult = await player.play(voiceChannel, bridged.result, {
          ...baseOptions,
          searchEngine: bridged.usedEngine,
          fallbackSearchEngine: QueryType.SOUNDCLOUD_SEARCH,
        });

        if (DEFAULT_AUTOPLAY && bridgedResult.queue.repeatMode === QueueRepeatMode.OFF) {
          bridgedResult.queue.setRepeatMode(QueueRepeatMode.AUTOPLAY);
        }

        return bridgedResult;
      }
    } catch {
      // ignore and throw original error below
    }

    // Reliability fallback: if YouTube extraction fails, retry with SoundCloud search.
    try {
      const soundcloudQuery = bridgeQuery || fallbackTextQuery;
      if (soundcloudQuery) {
        const sc = await searchWithFallbackEngines(soundcloudQuery, 'soundcloud', requestedBy, { strictMode });
        const scResult = await player.play(voiceChannel, sc.result, {
          ...baseOptions,
          searchEngine: sc.usedEngine,
          fallbackSearchEngine: QueryType.SOUNDCLOUD_SEARCH,
        });

        if (DEFAULT_AUTOPLAY && scResult.queue.repeatMode === QueueRepeatMode.OFF) {
          scResult.queue.setRepeatMode(QueueRepeatMode.AUTOPLAY);
        }

        return scResult;
      }
    } catch {
      // ignore and throw original error below
    }

    throw primaryError;
  }
}

function rememberRadioTrack(guildId, track) {
  if (!guildId || !track?.url) return;
  const recent = radioRecentTrackUrls.get(guildId) || [];
  radioRecentTrackUrls.set(guildId, [...recent.filter((url) => url !== track.url), track.url].slice(-30));
}

function getRecentRadioUrls(queue, guildId) {
  const history = queue?.history?.tracks?.map((track) => track?.url).filter(Boolean).slice(-20) || [];
  const recent = radioRecentTrackUrls.get(guildId) || [];
  const queued = queue?.tracks?.toArray?.().map((track) => track?.url).filter(Boolean) || [];
  const seen = new Set([...history, ...recent, ...queued]);
  for (const track of [...(queue?.history?.tracks || []), ...(queue?.tracks?.toArray?.() || [])]) {
    const identity = canonicalSongKey(track);
    if (identity) seen.add(`song:${identity}`);
  }
  return seen;
}

async function findRadioBatch(station, queue, guildId) {
  const queries = [...station.queries].sort(() => Math.random() - 0.5);
  const seen = getRecentRadioUrls(queue, guildId);
  const collected = [];
  const batchSeen = new Set();

  for (const query of queries.slice(0, 3)) {
    try {
      const result = await runSearch(query, 'auto', client.user);
      for (const track of result.tracks) {
        const durationMs = Number(track?.durationMS || 0);
        const identity = canonicalSongKey(track);
        if (!track?.url || track.live || durationMs > 15 * 60 * 1000 || isUnrequestedVariant(track, query) || seen.has(track.url) || seen.has(`song:${identity}`) || batchSeen.has(track.url) || batchSeen.has(`song:${identity}`)) continue;
        batchSeen.add(track.url);
        batchSeen.add(`song:${identity}`);
        collected.push(track);
      }
      if (collected.length >= 8) break;
    } catch (error) {
      if (process.env.PLAYER_DEBUG === 'true') console.warn(`[Radio Search] ${query}: ${error?.message || error}`);
    }
  }

  return collected.sort(() => Math.random() - 0.5).slice(0, 12);
}

async function refillRadioQueue(queue, stationId) {
  const guildId = queue?.guild?.id;
  const station = RADIO_STATIONS[stationId];
  if (!guildId || !station || radioFillLocks.has(guildId)) return false;

  const fillPromise = (async () => {
    const tracks = await findRadioBatch(station, queue, guildId);
    if (!tracks.length || getQueue(guildId) !== queue || radioStationsByGuild.get(guildId) !== stationId) return false;
    for (const track of tracks) {
      queue.addTrack(track);
      rememberRadioTrack(guildId, track);
    }
    if (!queue.isPlaying()) queue.node.play();
    console.log(`[Radio] Added ${tracks.length} fresh ${station.genre} tracks in guild ${guildId}.`);
    return true;
  })();
  radioFillLocks.set(guildId, fillPromise);
  try {
    return await fillPromise;
  } finally {
    radioFillLocks.delete(guildId);
  }
}

async function startRadioStation(voiceChannel, textChannel, requestedBy, stationId) {
  const station = RADIO_STATIONS[stationId];
  const guildId = voiceChannel.guild.id;
  const queue = getQueue(guildId);
  const tracks = await findRadioBatch(station, queue, guildId);
  if (!tracks.length) throw new Error(`No playable tracks were found for ${station.genre}. Please try again in a moment.`);

  const [firstTrack, ...upcoming] = tracks;
  radioStationsByGuild.set(guildId, stationId);
  for (const track of tracks) rememberRadioTrack(guildId, track);
  let result;
  try {
    result = await player.play(voiceChannel, firstTrack, {
      requestedBy,
      nodeOptions: createPlaybackNodeOptions({ textChannel, radioStationId: stationId }),
    });
  } catch (error) {
    radioStationsByGuild.delete(guildId);
    throw error;
  }

  result.queue.metadata.radioStationId = stationId;
  result.queue.setRepeatMode(QueueRepeatMode.OFF);
  for (const track of upcoming) result.queue.addTrack(track);
  return result;
}

async function refreshNowPlayingMessage(queue) {
  const entry = nowPlayingRegistry.get(queue.guild.id);
  if (!entry || entry.refreshing) return;
  entry.refreshing = true;
  try {
    let message = entry.message;
    if (!message) {
      const channel = await client.channels.fetch(entry.channelId).catch(() => null);
      if (!channel || !channel.isTextBased()) {
        nowPlayingRegistry.delete(queue.guild.id);
        return;
      }
      message = await channel.messages.fetch(entry.messageId).catch(() => null);
    }
    if (!message) {
      nowPlayingRegistry.delete(queue.guild.id);
      return;
    }

    try {
      await message.edit({
        components: [buildNowPlayingCard(queue)],
        flags: MessageFlags.IsComponentsV2,
      });
    } catch {
      await message.edit({
        embeds: [buildNowPlayingEmbed(queue)],
        components: [buildControlsRow(queue), buildLibraryControlsRow()],
      }).catch(() => null);
    }
  } catch {
    // A deleted or inaccessible message should not leave a permanent refresh loop.
    nowPlayingRegistry.delete(queue.guild.id);
  } finally {
    entry.refreshing = false;
  }
}

const nowPlayingRefreshTimer = setInterval(() => {
  for (const guildId of nowPlayingRegistry.keys()) {
    const queue = getQueue(guildId);
    if (!queue || !queue.currentTrack) {
      nowPlayingRegistry.delete(guildId);
      continue;
    }
    void refreshNowPlayingMessage(queue);
  }
}, 5_000);
nowPlayingRefreshTimer.unref?.();

function setNowPlayingRegistry(queue, message) {
  nowPlayingRegistry.set(queue.guild.id, {
    channelId: message.channel.id,
    messageId: message.id,
    message,
    refreshing: false,
  });
}

async function handleAutocomplete(interaction) {
  if (!interaction.isAutocomplete()) return false;

  const commandName = interaction.commandName;
  if (!['play', 'search'].includes(commandName)) {
    await interaction.respond([]).catch(() => null);
    return true;
  }

  const focused = interaction.options.getFocused(true);
  if (focused.name !== 'query') {
    await interaction.respond([]).catch(() => null);
    return true;
  }

  const query = String(focused.value || '').trim();
  if (query.length < 2) {
    await interaction.respond([]).catch(() => null);
    return true;
  }

  const platform = interaction.options.getString('platform') || 'auto';
  const strictOption = interaction.options.getBoolean('strict');
  const strictMode = resolveStrictMode(interaction.guildId, strictOption);

  try {
    const searchResult = await runSearch(query, platform, interaction.user, { strictMode });
    const tracks = searchResult.tracks.slice(0, MAX_AUTOCOMPLETE_CHOICES);

    const choices = tracks.map((track) => {
      const label = truncate(`${track.cleanTitle || track.title} - ${track.author || 'Unknown'}`, 100);
      const preferredValue =
        typeof track.url === 'string' && track.url.length > 0 && track.url.length <= 100
          ? track.url
          : `${track.cleanTitle || track.title || ''} ${track.author || ''}`.trim();
      const value = truncate(preferredValue || query, 100);
      return { name: label, value };
    });

    await interaction.respond(choices).catch(() => null);
  } catch {
    await interaction.respond([]).catch(() => null);
  }

  return true;
}

async function handlePlay(interaction) {
  if (shouldThrottlePlayCommand(interaction.guildId, interaction.user.id)) {
    await safeReplyEmbed(
      interaction,
      `${EMOJIS.warning} Cooldown Active`,
      'Please wait a moment before using `/play` again.',
      WARNING_COLOR,
      true
    );
    return;
  }

  const voiceCheck = await ensureVoiceAndPermissions(interaction);
  if (!voiceCheck.ok) return;

  const query = interaction.options.getString('query', true);
  const platform = interaction.options.getString('platform') || 'auto';
  const strictOption = interaction.options.getBoolean('strict');
  const strictMode = resolveStrictMode(interaction.guildId, strictOption);

  await interaction.deferReply();

  try {
    const { track, queue } = await queueAndPlay(voiceCheck.channel, query, interaction.channel, interaction.user, platform, { strictMode });

    const isCurrentlyPlaying = queue.currentTrack && (queue.currentTrack === track || queue.currentTrack.url === track.url);

    if (isCurrentlyPlaying) {
      await sendOrEditNowPlaying(interaction, queue, track);
      return;
    }

    const queuePosition = queue.tracks.toArray().findIndex((t) => t === track || t.url === track.url) + 1 || queue.size;
    const duration = track.live ? 'LIVE' : (track.duration || formatDurationMs(track.durationMS));
    const author = track.author || 'Unknown artist';
    const source = getSourceLabel(track);
    const title = track.cleanTitle || track.title;
    const linkedTitle = track.url ? `[${title}](${track.url})` : title;
    const currentPlaying = queue.currentTrack;
    const currentPlayingText = currentPlaying
      ? `**[${truncate(currentPlaying.cleanTitle || currentPlaying.title, 40)}](${currentPlaying.url || 'https://discord.com'})**`
      : 'None';

    const embed = new EmbedBuilder()
      .setColor(BRAND_COLOR)
      .setAuthor({ name: BRAND_NAME, iconURL: BRAND_LOGO_URL })
      .setTitle(`${EMOJIS.added} Track Added to Queue`)
      .setDescription(
        `**${linkedTitle}**\n\n` +
        `• **Position in Queue:** \`#${queuePosition}\`\n` +
        `• **Artist:** ${author}\n` +
        `• **Duration:** \`${duration}\`\n` +
        `• **Requested by:** <@${interaction.user.id}> • ${source}\n\n` +
        `▶ **Currently Playing:** ${currentPlayingText}`
      )
      .setThumbnail(track.thumbnail && /^https:\/\//i.test(track.thumbnail) ? track.thumbnail : BRAND_LOGO_URL)
      .setFooter({ text: `${BRAND_NAME} • ${queue.size} track(s) waiting in queue`, iconURL: BRAND_LOGO_URL })
      .setTimestamp();

    const queueRow = new ActionRowBuilder().addComponents(
      new ButtonBuilder()
        .setCustomId(BUTTON_IDS.QUEUE)
        .setStyle(ButtonStyle.Secondary)
        .setEmoji(getButtonEmoji(EMOJIS.queue, '📜'))
        .setLabel('View Queue'),
      new ButtonBuilder()
        .setCustomId(BUTTON_IDS.LIKE)
        .setStyle(ButtonStyle.Secondary)
        .setEmoji(getButtonEmoji(EMOJIS.heart, '💖'))
        .setLabel('Favorite')
    );

    await interaction.editReply({ embeds: [embed], components: [queueRow] });

    void refreshNowPlayingMessage(queue);
  } catch (error) {
    console.error('[Play Error]', error);
    const errEmbed = createNotificationEmbed(
      `${EMOJIS.refused} Could Not Play Track`,
      `${error.message || error}`,
      ERROR_COLOR
    );
    await interaction.editReply({ embeds: [errEmbed] });
  }
}

async function handleSearch(interaction) {
  const query = interaction.options.getString('query', true);
  const platform = interaction.options.getString('platform') || 'auto';
  const strictOption = interaction.options.getBoolean('strict');
  const strictMode = resolveStrictMode(interaction.guildId, strictOption);

  await interaction.deferReply({ flags: MessageFlags.Ephemeral });

  try {
    const searchResult = await runSearch(query, platform, interaction.user, { strictMode });
    const tracks = searchResult.tracks.slice(0, 10);
    const sessionId = interaction.id;
    searchSessions.set(sessionId, { userId: interaction.user.id, guildId: interaction.guildId, tracks, expiresAt: Date.now() + 120_000 });
    if (searchSessions.size > 200) {
      for (const [id, session] of searchSessions) if (session.expiresAt < Date.now()) searchSessions.delete(id);
    }
    await interaction.editReply({
      embeds: [buildSearchEmbed(query, platform, tracks)],
      components: buildSearchResultRows(sessionId, tracks),
    });
  } catch (error) {
    console.error('[Search Error]', error);
    await safeReplyEmbed(interaction, `${EMOJIS.refused} Search Failed`, `${error.message || error}`, ERROR_COLOR, true);
  }
}

async function handleStrictMode(interaction) {
  const mode = interaction.options.getString('mode', true);
  const enabled = mode === 'on';
  setGuildStrictMode(interaction.guildId, enabled);

  await safeReplyEmbed(
    interaction,
    `${EMOJIS.approved} Strict Mode: ${enabled ? 'ENABLED' : 'DISABLED'}`,
    `Strict song matching is now **${enabled ? 'ON' : 'OFF'}** for this server.`,
    enabled ? SUCCESS_COLOR : BRAND_COLOR,
    true,
  );
}

async function handlePlaylist(interaction) {
  const subcommand = interaction.options.getSubcommand();
  const favorites = getUserFavorites(interaction.user.id);

  if (subcommand === 'show') {
    await safeReply(interaction, {
      embeds: [buildFavoritesEmbed(interaction.user, favorites)],
      flags: MessageFlags.Ephemeral,
    });
    return;
  }

  if (subcommand === 'clear') {
    const removed = clearFavorites(interaction.user.id);
    await safeReplyEmbed(
      interaction,
      removed > 0 ? `${EMOJIS.approved} Playlist Cleared` : `${EMOJIS.warning} Playlist Empty`,
      removed > 0 ? `Cleared **${removed}** track(s) from your liked playlist.` : 'Your liked playlist is already empty.',
      removed > 0 ? SUCCESS_COLOR : BRAND_COLOR,
      true
    );
    return;
  }

  if (subcommand === 'remove') {
    const position = interaction.options.getInteger('track', true);
    const { removed, total } = removeFavoriteByIndex(interaction.user.id, position);

    if (!removed) {
      await safeReplyEmbed(interaction, `${EMOJIS.refused} Invalid Track`, 'That track number does not exist in your playlist.', WARNING_COLOR, true);
      return;
    }

    await safeReplyEmbed(
      interaction,
      `${EMOJIS.approved} Track Removed`,
      `Removed **${removed.title}** from your playlist.\n**${total}** track(s) remaining in your playlist.`,
      BRAND_COLOR,
      true
    );
    return;
  }

  if (subcommand === 'play') {
    if (!favorites.length) {
      await safeReplyEmbed(
        interaction,
        `${EMOJIS.warning} Playlist Empty`,
        `Your liked playlist is empty. Click the **${EMOJIS.heart} Favorite** button while music plays to save tracks first.`,
        WARNING_COLOR,
        true
      );
      return;
    }

    const voiceCheck = await ensureVoiceAndPermissions(interaction);
    if (!voiceCheck.ok) return;

    await interaction.deferReply();

    try {
      const first = favorites[0];
      const firstQuery = first.url || first.title;
      const { queue } = await queueAndPlay(voiceCheck.channel, firstQuery, interaction.channel, interaction.user, 'auto');

      let added = 0;
      for (const favorite of favorites.slice(1, MAX_PLAYLIST_LOAD)) {
        const query = favorite.url || favorite.title;
        const result = await runSearch(query, 'auto', interaction.user);
        if (result.hasTracks()) {
          queue.addTrack(result.tracks[0]);
          added += 1;
        }
      }

      await interaction.editReply({
        embeds: [
          createNotificationEmbed(
            `${EMOJIS.playlist} Playlist Loaded`,
            `Loaded favorites playlist: playing **${favorites[0].title}** and queued **${added}** additional track(s).`,
            SUCCESS_COLOR
          )
        ]
      });
    } catch (error) {
      console.error('[Playlist Play Error]', error);
      await interaction.editReply({
        embeds: [
          createNotificationEmbed(
            `${EMOJIS.refused} Playlist Error`,
            `Could not load your playlist: ${error.message || error}`,
            ERROR_COLOR
          )
        ]
      });
    }
  }
}

async function handleRadio(interaction) {
  const stationKey = interaction.options.getString('station', true);
  const station = RADIO_STATIONS[stationKey];
  if (!station) {
    await safeReplyEmbed(interaction, `${EMOJIS.warning} Station Not Found`, 'Unknown radio station selected.', WARNING_COLOR, true);
    return;
  }

  const voiceCheck = await ensureVoiceAndPermissions(interaction);
  if (!voiceCheck.ok) return;

  await interaction.deferReply();

  try {
    const { track, queue } = await startRadioStation(
      voiceCheck.channel, interaction.channel, interaction.user, stationKey,
    );

    const embed = new EmbedBuilder()
      .setColor(BRAND_COLOR)
      .setAuthor({ name: BRAND_NAME, iconURL: BRAND_LOGO_URL })
      .setTitle(`${EMOJIS.radio} Genre Radio Online`)
      .setDescription(
        `Now tuned into **${station.name}**\n\n` +
        `• **Genre / Style:** \`${station.genre}\`\n` +
        `• **Rotation:** Endless official tracks with anti-repetition protection\n\n` +
        `${EMOJIS.syncinkmusic} *The station automatically discovers and plays fresh music 24/7.*`
      )
      .setFooter({ text: `${BRAND_NAME} • Station Discovery`, iconURL: BRAND_LOGO_URL })
      .setTimestamp();

    await interaction.editReply({ embeds: [embed] });
  } catch (error) {
    console.error('[Radio Play Error]', error);
    await interaction.editReply({
      embeds: [
        createNotificationEmbed(
          `${EMOJIS.refused} Radio Offline`,
          `Failed to start radio stream: ${error.message || error}`,
          ERROR_COLOR
        )
      ]
    });
  }
}

async function handleLofi(interaction) {
  const voiceCheck = await ensureVoiceAndPermissions(interaction);
  if (!voiceCheck.ok) return;

  await interaction.deferReply();

  const lofiStation = RADIO_STATIONS.lofi;
  try {
    const { track, queue } = await startRadioStation(
      voiceCheck.channel, interaction.channel, interaction.user, 'lofi',
    );

    const embed = new EmbedBuilder()
      .setColor(BRAND_COLOR)
      .setAuthor({ name: BRAND_NAME, iconURL: BRAND_LOGO_URL })
      .setTitle(`${EMOJIS.radio} 24/7 Lofi Stream Online`)
      .setDescription(
        `Now streaming **${lofiStation.name}**\n\n` +
        `• **Genre / Style:** \`${lofiStation.genre}\`\n` +
        `• **Vibe:** Relaxing, studying, and focus instrumental beats\n` +
        `• **Rotation:** Anti-speech and no-talking filters enabled\n\n` +
        `${EMOJIS.syncinkmusic} *Continuous 24/7 stream. Use \`/stop\` or \`/leave\` to disconnect.*`
      )
      .setFooter({ text: `${BRAND_NAME} • Lofi Chill Radio`, iconURL: BRAND_LOGO_URL })
      .setTimestamp();

    await interaction.editReply({ embeds: [embed] });
  } catch (error) {
    console.error('[Lofi Play Error]', error);
    await interaction.editReply({
      embeds: [
        createNotificationEmbed(
          `${EMOJIS.refused} Lofi Offline`,
          `Could not start lofi stream: ${error.message || error}`,
          ERROR_COLOR
        )
      ]
    });
  }
}

async function handle247(interaction, queue) {
  const mode = interaction.options.getString('mode', true);
  const guildId = interaction.guildId;

  if (mode === 'on') {
    twentyFourSevenGuilds.add(guildId);
    if (emptyVcTimers.has(guildId)) {
      clearTimeout(emptyVcTimers.get(guildId));
      emptyVcTimers.delete(guildId);
    }

    if (queue) {
      if (!radioStationsByGuild.has(guildId) && queue.repeatMode === QueueRepeatMode.OFF) {
        queue.setRepeatMode(QueueRepeatMode.AUTOPLAY);
      }
    }

    await safeReplyEmbed(
      interaction,
      `${EMOJIS.radio} 24/7 Mode: ACTIVATED`,
      `The bot will now play continuously and stay in the voice channel indefinitely.\n\n` +
      `• **Continuous Refill:** Endless queue discovery stays active.\n` +
      `• **Voice Channel:** Stays connected even when users leave or disconnect.\n\n` +
      `Use \`/247 mode:off\` or \`/leave\` to deactivate.`,
      SUCCESS_COLOR
    );
    return;
  }

  disableContinuousPlayback(guildId, queue);
  if (queue?.channel && queue.channel.members.filter((member) => !member.user.bot).size === 0) {
    queue.delete();
    nowPlayingRegistry.delete(guildId);
  }
  await safeReplyEmbed(
    interaction,
    `${EMOJIS.pause} 24/7 Mode: DEACTIVATED`,
    'The bot will now stop when the queue finishes or the voice channel is empty.',
    BRAND_COLOR
  );
}

async function handleTaste(interaction) {
  if (!interaction.inGuild()) {
    await safeReply(interaction, { content: 'Music taste profiles are managed per server.', flags: MessageFlags.Ephemeral });
    return;
  }

  const mode = interaction.options.getString('mode', true);
  const guildId = interaction.guildId;
  const userId = interaction.user.id;

  if (mode === 'on') {
    const priorProfile = musicTaste.getProfile(guildId, userId);
    musicTaste.setEnabled(guildId, userId, true);
    if (!priorProfile?.favoritesImported) {
      for (const favorite of getUserFavorites(userId)) {
        musicTaste.recordTrack(guildId, userId, { title: favorite.title, author: favorite.author }, 3, 'like');
      }
      musicTaste.markFavoritesImported(guildId, userId);
    }
    const aiMessage = OPENAI_API_KEY
      ? 'With AI enabled, a taste summary and candidate song titles/artists are sent to OpenAI to rank recommendations. Discord IDs and usernames are not sent.'
      : 'AI ranking is currently off because OPENAI_API_KEY is not configured; local taste ranking still works.';
    await safeReplyEmbed(
      interaction,
      '🎧 Music Taste: Enabled',
      `This server will learn from tracks you finish and songs you explicitly like. Your profile is stored locally for this server. ${aiMessage}\n\nUse /taste mode:off to pause learning, or /taste mode:forget to erase your profile.`,
      SUCCESS_COLOR,
      true,
    );
    return;
  }

  if (mode === 'off') {
    musicTaste.setEnabled(guildId, userId, false);
    await safeReplyEmbed(interaction, '🎧 Music Taste: Paused', 'Taste learning and personalized AI recommendations are paused. Your saved profile remains until you use `/taste mode:forget`.', BRAND_COLOR, true);
    return;
  }

  if (mode === 'forget') {
    const existed = musicTaste.forget(guildId, userId);
    await safeReplyEmbed(interaction, '🧹 Music Taste: Erased', existed ? 'Your per-server taste profile has been deleted.' : 'There was no saved taste profile for this server.', BRAND_COLOR, true);
    return;
  }

  const profile = musicTaste.getProfile(guildId, userId);
  const enabled = profile?.enabled === true;
  const artists = Object.keys(profile?.artists || {}).length;
  const interests = Object.keys(profile?.terms || {}).length;
  const status = enabled ? 'Enabled' : profile ? 'Paused' : 'Not set up';
  await safeReplyEmbed(
    interaction,
    '🎧 Your Music Taste Profile',
    `**Status:** ${status}\n**Artists learned:** ${artists}\n**Music interests:** ${interests}\n**AI ranking:** ${enabled && OPENAI_API_KEY ? `Ready (${OPENAI_MODEL})` : 'Local ranking only'}\n\nUse /taste mode:on, off, status, or forget.`,
    BRAND_COLOR,
    true,
  );
}

async function handleUpdate(interaction) {
  // Check permission: Administrator or Guild Owner
  const isOwner = interaction.guild && interaction.guild.ownerId === interaction.user.id;
  const isAdmin = interaction.memberPermissions && interaction.memberPermissions.has(PermissionFlagsBits.Administrator);

  if (!isOwner && !isAdmin) {
    await safeReplyEmbed(
      interaction,
      '⛔ Permission Denied',
      'Only the server administrator or server owner can run `/update`.',
      ERROR_COLOR,
      true,
    );
    return;
  }

  await interaction.deferReply();

  await interaction.editReply({
    embeds: [
      createNotificationEmbed(
        '🔄 Checking for Updates...',
        'Connecting to GitHub and pulling the latest changes to your Termux phone...',
        BRAND_COLOR,
      ),
    ],
  });

  exec('git pull', { cwd: __dirname }, async (error, stdout, stderr) => {
    if (error) {
      console.error('[Update Error]', error, stderr);
      await interaction.editReply({
        embeds: [
          createNotificationEmbed(
            '❌ Update Failed',
            `Failed to pull updates from GitHub:\n\`\`\`\n${truncate(error.message || stderr || 'Unknown git error', 1000)}\n\`\`\``,
            ERROR_COLOR,
          ),
        ],
      });
      return;
    }

    const output = String(stdout || '').trim();
    const isAlreadyUpToDate = output.includes('Already up to date');

    if (isAlreadyUpToDate) {
      await interaction.editReply({
        embeds: [
          createNotificationEmbed(
            '✅ Already Up to Date',
            'Your bot is already running the latest commit from GitHub!\n\nNo restart required.',
            SUCCESS_COLOR,
          ),
        ],
      });
      return;
    }

    await interaction.editReply({
      embeds: [
        createNotificationEmbed(
          '🚀 Update Downloaded Successfully',
          `Pulled latest updates from GitHub!\n\`\`\`\n${truncate(output, 500)}\n\`\`\`\n*Installing updated packages (mediaplex & @evan/opus) & restarting...*`,
          SUCCESS_COLOR,
        ),
      ],
    });

    exec('npm install --omit=dev', { cwd: __dirname }, (npmErr) => {
      if (npmErr) console.warn('[Auto-Update npm install]', npmErr.message);
      setTimeout(() => {
        console.log('[Auto-Update] Restarting process to load fresh code...');
        process.exit(0);
      }, 2000);
    });
  });
}

async function handleFilterCommand(interaction, queue) {
  const filterChoice = interaction.options.getString('type', true);

  const filtersToApply = {
    bassboost_low: false,
    bassboost: false,
    bassboost_high: false,
    '8D': false,
    nightcore: false,
    vaporwave: false,
    karaoke: false,
    normalizer: false,
  };

  if (filterChoice === 'off') {
    await queue.filters.ffmpeg.setFilters(filtersToApply);
    await safeReplyEmbed(interaction, `${EMOJIS.syncvolume} Filters Cleared`, 'All audio effects and DSP filters have been reset to normal.', BRAND_COLOR);
    return;
  }

  filtersToApply[filterChoice] = true;
  await queue.filters.ffmpeg.setFilters(filtersToApply);

  const names = {
    bassboost: 'Bassboost (Normal)',
    bassboost_high: 'Bassboost (Ear-shaking High)',
    '8D': '8D Surround Audio',
    nightcore: 'Nightcore (Speed & Pitch Boost)',
    vaporwave: 'Vaporwave (Slowed & Reverb)',
    karaoke: 'Karaoke (Vocal Suppression)',
    normalizer: 'Dynamic Normalizer',
  };

  await safeReplyEmbed(
    interaction,
    `${EMOJIS.syncvolume} Audio Effect Applied`,
    `Applied **${names[filterChoice] || filterChoice}** successfully!`,
    BRAND_COLOR,
  );
}

async function handleLyrics(interaction, queue) {
  const customQuery = interaction.options.getString('query');
  const query = customQuery || (queue?.currentTrack ? `${queue.currentTrack.title} ${queue.currentTrack.author || ''}`.trim() : null);

  if (!query) {
    await safeReplyEmbed(interaction, `${EMOJIS.warning} Missing Song Name`, 'Provide a song name or play a track first to search lyrics.', WARNING_COLOR, true);
    return;
  }

  await interaction.deferReply({ flags: MessageFlags.Ephemeral });

  try {
    const results = await player.lyrics.search({ q: query });
    const first = results?.[0];

    if (!first || !first.plainLyrics) {
      await interaction.editReply({ embeds: [createNotificationEmbed(`${EMOJIS.warning} No Lyrics Found`, `Could not find lyrics for **${truncate(query, 80)}**.`, WARNING_COLOR)] });
      return;
    }

    await interaction.editReply({
      embeds: [buildLyricsEmbed(query, first)],
    });
  } catch (error) {
    console.error('[Lyrics Error]', error);
    await interaction.editReply({ embeds: [createNotificationEmbed(`${EMOJIS.refused} Lyrics Error`, `${error.message || error}`, ERROR_COLOR)] });
  }
}

async function handleLoop(interaction, queue) {
  const mode = interaction.options.getString('mode', true);

  if (mode === 'all') {
    queue.setRepeatMode(QueueRepeatMode.QUEUE);
    await safeReplyEmbed(interaction, `${EMOJIS.approved} Loop Mode: QUEUE`, 'Now looping the entire queue continuously.', SUCCESS_COLOR);
    return;
  }

  if (mode === 'current') {
    queue.setRepeatMode(QueueRepeatMode.TRACK);
    await safeReplyEmbed(interaction, `${EMOJIS.approved} Loop Mode: CURRENT TRACK`, 'Now repeating the current song continuously.', SUCCESS_COLOR);
    return;
  }

  queue.setRepeatMode(QueueRepeatMode.OFF);
  await safeReplyEmbed(interaction, `${EMOJIS.approved} Loop Mode: DISABLED`, 'Looping turned off. Playback will advance normally.', BRAND_COLOR);
}

async function handleAutoplay(interaction, queue) {
  const mode = interaction.options.getString('mode', true);

  if (mode === 'on') {
    queue.setRepeatMode(QueueRepeatMode.AUTOPLAY);
    await safeReplyEmbed(interaction, `${EMOJIS.radio} Autoplay: ENABLED`, 'Autoplay is now on. Recommended related tracks will play automatically when queue ends.', SUCCESS_COLOR);
    return;
  }

  queue.setRepeatMode(QueueRepeatMode.OFF);
  await safeReplyEmbed(interaction, `${EMOJIS.stop} Autoplay: DISABLED`, 'Autoplay turned off.', BRAND_COLOR);
}

async function handleBassBoost(interaction, queue) {
  const mode = interaction.options.getString('mode', true);

  const filterState = {
    bassboost_low: false,
    bassboost: false,
    bassboost_high: false,
  };

  if (mode === 'low') filterState.bassboost_low = true;
  if (mode === 'normal') filterState.bassboost = true;
  if (mode === 'high') filterState.bassboost_high = true;

  await queue.filters.ffmpeg.setFilters(filterState);
  const label = mode === 'off' ? 'Disabled' : `Set to ${mode.toUpperCase()}`;
  await safeReplyEmbed(interaction, `${EMOJIS.syncvolume} Bassboost: ${label}`, `Bassboost profile has been updated to **${mode}**.`, BRAND_COLOR);
}

async function handle8D(interaction, queue) {
  const mode = interaction.options.getString('mode', true);

  if (mode === 'on') {
    await queue.filters.ffmpeg.setFilters({ '8D': true });
    await safeReplyEmbed(interaction, `${EMOJIS.syncvolume} 8D Audio: ON`, '8D spatial audio rotation effect has been enabled.', SUCCESS_COLOR);
    return;
  }

  await queue.filters.ffmpeg.setFilters({ '8D': false });
  await safeReplyEmbed(interaction, `${EMOJIS.syncvolume} 8D Audio: OFF`, '8D spatial audio effect disabled.', BRAND_COLOR);
}

async function handleQueueSubcommands(interaction, queue) {
  const subcommand = interaction.options.getSubcommand();

  if (subcommand === 'list') {
    if (!hasActiveTrack(queue)) {
      await safeReplyEmbed(interaction, `${EMOJIS.queue} Queue is Empty`, 'No tracks are currently queued. Add tracks with `/play` or tune into `/radio`.', BRAND_COLOR, true);
      return;
    }

    await safeReply(interaction, { embeds: [buildQueueEmbed(queue)] });
    return;
  }

  if (subcommand === 'clear') {
    if (!queue || queue.size === 0) {
      await safeReplyEmbed(interaction, `${EMOJIS.queue} Queue is Already Empty`, 'There are no upcoming tracks to clear.', BRAND_COLOR, true);
      return;
    }

    queue.clear();
    await safeReplyEmbed(interaction, `${EMOJIS.approved} Queue Cleared`, 'All upcoming tracks have been removed from the queue.', SUCCESS_COLOR);
  }
}

async function handleCommandInteraction(interaction) {
  if (!interaction.isChatInputCommand()) return;

  try {
    if (interaction.commandName === 'invite') {
      if (!CLIENT_ID) throw new Error('Set DISCORD_CLIENT_ID to generate your server install link.');
      const permissions = [
        PermissionFlagsBits.ViewChannel, PermissionFlagsBits.SendMessages, PermissionFlagsBits.EmbedLinks,
        PermissionFlagsBits.ReadMessageHistory, PermissionFlagsBits.Connect, PermissionFlagsBits.Speak,
        PermissionFlagsBits.UseVAD, PermissionFlagsBits.UseExternalEmojis,
      ].reduce((all, bit) => all | bit, 0n);
      const params = new URLSearchParams({ client_id: CLIENT_ID, permissions: permissions.toString(), scope: 'bot applications.commands' });
      await safeReplyEmbed(
        interaction,
        `${EMOJIS.syncink} Invite ${BRAND_NAME}`,
        `Add **${BRAND_NAME}** to your Discord server:\n\n[**Click Here to Authorize & Invite**](https://discord.com/oauth2/authorize?${params})`,
        BRAND_COLOR,
        true
      );
      return;
    }

    if (interaction.commandName === 'play') {
      await handlePlay(interaction);
      return;
    }

    if (interaction.commandName === 'search') {
      await handleSearch(interaction);
      return;
    }

    if (interaction.commandName === 'radio') {
      await handleRadio(interaction);
      return;
    }

    if (interaction.commandName === 'lofi') {
      await handleLofi(interaction);
      return;
    }

    if (interaction.commandName === 'help') {
      await safeReply(interaction, { embeds: [buildHelpEmbed()], flags: MessageFlags.Ephemeral });
      return;
    }

    if (interaction.commandName === 'taste') {
      await handleTaste(interaction);
      return;
    }

    if (!interaction.inGuild()) {
      await safeReplyEmbed(interaction, `${EMOJIS.refused} Server Only`, 'This command can only be used in a Discord server.', ERROR_COLOR, true);
      return;
    }

    const queue = getQueue(interaction.guildId);

    if (interaction.commandName === 'playlist') {
      await handlePlaylist(interaction);
      return;
    }

    if (interaction.commandName === 'strict') {
      await handleStrictMode(interaction);
      return;
    }

    if (interaction.commandName === 'lyrics') {
      await handleLyrics(interaction, queue);
      return;
    }

    if (interaction.commandName === 'queue') {
      await handleQueueSubcommands(interaction, queue);
      return;
    }

    if (interaction.commandName === 'np') {
      if (!hasActiveTrack(queue)) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} Nothing Playing`, 'Nothing is currently playing.', BRAND_COLOR, true);
        return;
      }

      try {
        await safeReply(interaction, {
          components: [buildNowPlayingCard(queue)],
          flags: MessageFlags.IsComponentsV2,
        });
      } catch {
        await safeReply(interaction, {
          embeds: [buildNowPlayingEmbed(queue)],
          components: [buildControlsRow(queue), buildLibraryControlsRow()],
        });
      }
      return;
    }

    if (interaction.commandName === 'leave') {
      if (!queue) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} Not Connected`, 'I am not currently connected to any voice channel.', ERROR_COLOR, true);
        return;
      }

      disableContinuousPlayback(interaction.guildId, queue);
      queue.delete();
      radioRecentTrackUrls.delete(interaction.guildId);
      nowPlayingRegistry.delete(interaction.guildId);
      await safeReplyEmbed(interaction, `${EMOJIS.stop} Disconnected`, 'Left the voice channel and cleared the session.', BRAND_COLOR);
      return;
    }

    if (interaction.commandName === 'stop') {
      if (!hasActiveTrack(queue)) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} Nothing Playing`, 'No track is currently playing.', BRAND_COLOR, true);
        return;
      }

      if (!(await ensureSameVoiceChannel(interaction, queue))) return;
      disableContinuousPlayback(interaction.guildId, queue);
      queue.node.stop();
      await safeReplyEmbed(interaction, `${EMOJIS.stop} Playback Stopped`, 'Stopped music playback and cleared active audio.', BRAND_COLOR);
      return;
    }

    if (!queue) {
      await safeReplyEmbed(interaction, `${EMOJIS.warning} No Active Queue`, 'There is no music queue active. Start by using `/play` or `/radio`.', BRAND_COLOR, true);
      return;
    }

    if (!(await ensureSameVoiceChannel(interaction, queue))) return;

    if (interaction.commandName === 'pause') {
      if (!hasActiveTrack(queue)) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} Nothing Playing`, 'Nothing is currently playing.', BRAND_COLOR, true);
        return;
      }

      if (queue.node.isPaused()) {
        await safeReplyEmbed(interaction, `${EMOJIS.pause} Already Paused`, 'Playback is already paused.', WARNING_COLOR, true);
        return;
      }

      queue.node.pause();
      await safeReplyEmbed(interaction, `${EMOJIS.pause} Playback Paused`, 'Music paused. Resume anytime with `/resume`.', BRAND_COLOR);
      await refreshNowPlayingMessage(queue);
      return;
    }

    if (interaction.commandName === 'resume') {
      if (!hasActiveTrack(queue)) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} Nothing Playing`, 'Nothing is currently playing.', BRAND_COLOR, true);
        return;
      }

      if (!queue.node.isPaused()) {
        await safeReplyEmbed(interaction, `${EMOJIS.play} Already Playing`, 'Music playback is already running.', WARNING_COLOR, true);
        return;
      }

      queue.node.resume();
      await safeReplyEmbed(interaction, `${EMOJIS.play} Playback Resumed`, 'Resumed playing track.', SUCCESS_COLOR);
      await refreshNowPlayingMessage(queue);
      return;
    }

    if (interaction.commandName === 'skip') {
      if (!hasActiveTrack(queue)) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} Nothing Playing`, 'Nothing is currently playing to skip.', BRAND_COLOR, true);
        return;
      }

      const amount = interaction.options.getInteger('count') || 1;
      let skipped = 0;

      for (let i = 0; i < amount; i += 1) {
        if (queue.node.skip()) skipped += 1;
        else break;
      }

      if (skipped > 0) {
        await safeReplyEmbed(interaction, `${EMOJIS.skip} Track Skipped`, `Skipped **${skipped}** track(s) forward.`, SUCCESS_COLOR);
      } else {
        await safeReplyEmbed(interaction, `${EMOJIS.refused} Could Not Skip`, 'Unable to skip the current track.', ERROR_COLOR, true);
      }
      return;
    }

    if (interaction.commandName === 'shuffle') {
      if (queue.size < 2) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} Queue Too Short`, 'You need at least 2 tracks in the queue to shuffle.', WARNING_COLOR, true);
        return;
      }

      queue.tracks.shuffle();
      await safeReplyEmbed(interaction, `${EMOJIS.approved} Queue Shuffled`, `Randomized the order of **${queue.size}** upcoming tracks.`, SUCCESS_COLOR);
      return;
    }

    if (interaction.commandName === 'loop') {
      await handleLoop(interaction, queue);
      return;
    }

    if (interaction.commandName === 'autoplay') {
      await handleAutoplay(interaction, queue);
      return;
    }

    if (interaction.commandName === 'volume') {
      const value = interaction.options.getInteger('percent', true);
      let changed = queue.node.setVolume(value);
      if (!changed && queue.currentTrack) {
        // Direct Opus passthrough deliberately has no gain stage. Turn it on
        // only when volume is explicitly requested, then resume at live time.
        const position = queue.node.getTimestamp()?.current.value || 1;
        queue.options.disableVolume = false;
        queue.options.volume = value;
        const restarted = await queue.node.seek(Math.max(1, position));
        changed = restarted && queue.node.setVolume(value);
      }
      if (changed) {
        await safeReplyEmbed(interaction, `${EMOJIS.syncvolume} Volume Adjusted`, `Volume set to **${value}%**.`, BRAND_COLOR);
      } else {
        await safeReplyEmbed(interaction, `${EMOJIS.refused} Volume Error`, 'Could not change volume.', ERROR_COLOR, true);
      }
      return;
    }

    if (interaction.commandName === 'remove') {
      const position = interaction.options.getInteger('position', true);
      const track = queue.tracks.at(position - 1);

      if (!track) {
        await safeReplyEmbed(interaction, `${EMOJIS.refused} Invalid Position`, 'That position does not exist in the queue.', WARNING_COLOR, true);
        return;
      }

      queue.node.remove(track);
      await safeReplyEmbed(interaction, `${EMOJIS.approved} Track Removed`, `Removed **${track.cleanTitle || track.title}** from the queue.`, BRAND_COLOR);
      return;
    }

    if (interaction.commandName === 'replay') {
      if (!hasActiveTrack(queue)) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} Nothing Playing`, 'Nothing is currently playing.', BRAND_COLOR, true);
        return;
      }

      await queue.node.seek(0);
      await safeReplyEmbed(interaction, `${EMOJIS.previous} Replaying Track`, `Replaying **${queue.currentTrack?.title}** from the start.`, BRAND_COLOR);
      return;
    }

    if (interaction.commandName === 'seek') {
      if (!hasActiveTrack(queue)) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} Nothing Playing`, 'Nothing is currently playing to seek in.', BRAND_COLOR, true);
        return;
      }

      const input = interaction.options.getString('position', true);
      const targetMs = parseTimeToMs(input);

      if (targetMs == null) {
        await safeReplyEmbed(interaction, `${EMOJIS.refused} Invalid Timestamp`, 'Invalid seek format. Use `90`, `1:30`, or `00:01:30`.', WARNING_COLOR, true);
        return;
      }

      const current = queue.currentTrack;
      const durationMs = current?.durationMS || 0;

      if (!current?.live && durationMs > 0 && targetMs > durationMs) {
        await safeReplyEmbed(interaction, `${EMOJIS.refused} Beyond Track Length`, `Seek time is beyond track duration (${formatDurationMs(durationMs)}).`, WARNING_COLOR, true);
        return;
      }

      const ok = await queue.node.seek(targetMs);
      if (ok) {
        await safeReplyEmbed(interaction, `${EMOJIS.time} Seek Position`, `Seeked playback to **${formatDurationMs(targetMs)}**.`, SUCCESS_COLOR);
      } else {
        await safeReplyEmbed(interaction, `${EMOJIS.refused} Seek Failed`, 'Could not seek this track.', ERROR_COLOR, true);
      }
      return;
    }

    if (interaction.commandName === 'previous') {
      if (!queue.history.previousTrack) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} No History`, 'There is no previous track in listening history.', BRAND_COLOR, true);
        return;
      }

      await queue.history.previous();
      await safeReplyEmbed(interaction, `${EMOJIS.previous} Previous Track`, 'Jumped back to the previous track in history.', SUCCESS_COLOR);
      return;
    }

    if (interaction.commandName === 'bassboost') {
      await handleBassBoost(interaction, queue);
      return;
    }

    if (interaction.commandName === '8d') {
      await handle8D(interaction, queue);
      return;
    }

    if (interaction.commandName === '247') {
      await handle247(interaction, queue);
      return;
    }

    if (interaction.commandName === 'filter') {
      await handleFilterCommand(interaction, queue);
      return;
    }

    if (interaction.commandName === 'update') {
      await handleUpdate(interaction);
      return;
    }
  } catch (error) {
    console.error('[Interaction Error]', error);
    await safeReplyEmbed(interaction, `${EMOJIS.refused} Error`, `An error occurred: ${error.message || error}`, ERROR_COLOR, true);
  }
}

async function handleButtonInteraction(interaction) {
  if (!interaction.isButton()) return;

  const cancelMatch = interaction.customId.match(/^syncink_search_cancel:(\d+)$/);
  if (cancelMatch) {
    const [, sessionId] = cancelMatch;
    const session = searchSessions.get(sessionId);
    if (session) {
      if (interaction.user.id !== session.userId) {
        await safeReplyEmbed(interaction, `${EMOJIS.refused} Action Denied`, 'Only the user who started this search can cancel it.', ERROR_COLOR, true);
        return;
      }
      searchSessions.delete(sessionId);
    }
    await interaction.update({
      embeds: [createNotificationEmbed(`${EMOJIS.refused} Search Cancelled`, 'The search menu has been closed.', BRAND_COLOR)],
      components: [],
    }).catch(async () => {
      await safeReplyEmbed(interaction, `${EMOJIS.refused} Search Cancelled`, 'The search menu has been closed.', BRAND_COLOR, true);
    });
    return;
  }

  const pickMatch = interaction.customId.match(/^syncink_search_pick:(\d+):(\d+)$/);
  if (pickMatch) {
    const [, sessionId, indexText] = pickMatch;
    const session = searchSessions.get(sessionId);
    if (!session || session.expiresAt < Date.now()) {
      searchSessions.delete(sessionId);
      await safeReplyEmbed(interaction, `${EMOJIS.warning} Results Expired`, 'These search results expired. Run `/search` again.', WARNING_COLOR, true);
      return;
    }
    if (interaction.user.id !== session.userId || interaction.guildId !== session.guildId) {
      await safeReplyEmbed(interaction, `${EMOJIS.refused} Action Denied`, 'Only the person who opened these search results can select a track.', ERROR_COLOR, true);
      return;
    }
    const track = session.tracks[Number(indexText)];
    if (!track) {
      await safeReplyEmbed(interaction, `${EMOJIS.warning} Track Unavailable`, 'That search result is no longer available.', WARNING_COLOR, true);
      return;
    }
    const voiceCheck = await ensureVoiceAndPermissions(interaction);
    if (!voiceCheck.ok) return;
    searchSessions.delete(sessionId);
    await interaction.deferReply({ flags: MessageFlags.Ephemeral });
    try {
      const result = await player.play(voiceCheck.channel, track, {
        requestedBy: interaction.user,
        nodeOptions: createPlaybackNodeOptions({ textChannel: interaction.channel }),
      });
      if (DEFAULT_AUTOPLAY && result.queue.repeatMode === QueueRepeatMode.OFF) result.queue.setRepeatMode(QueueRepeatMode.AUTOPLAY);

      const isCurrentlyPlaying = result.queue.currentTrack && (result.queue.currentTrack === track || result.queue.currentTrack.url === track.url);

      if (isCurrentlyPlaying) {
        await sendOrEditNowPlaying(interaction, result.queue, track);
        return;
      }

      const queuePosition = result.queue.tracks.toArray().findIndex((t) => t === track || t.url === track.url) + 1 || result.queue.size;
      const duration = track.live ? 'LIVE' : (track.duration || formatDurationMs(track.durationMS));
      const author = track.author || 'Unknown artist';
      const source = getSourceLabel(track);
      const title = track.cleanTitle || track.title;
      const linkedTitle = track.url ? `[${title}](${track.url})` : title;
      const currentPlaying = result.queue.currentTrack;
      const currentPlayingText = currentPlaying
        ? `**[${truncate(currentPlaying.cleanTitle || currentPlaying.title, 40)}](${currentPlaying.url || 'https://discord.com'})**`
        : 'None';

      const embed = new EmbedBuilder()
        .setColor(BRAND_COLOR)
        .setAuthor({ name: BRAND_NAME, iconURL: BRAND_LOGO_URL })
        .setTitle(`${EMOJIS.added} Track Added to Queue`)
        .setDescription(
          `**${linkedTitle}**\n\n` +
          `• **Position in Queue:** \`#${queuePosition}\`\n` +
          `• **Artist:** ${author}\n` +
          `• **Duration:** \`${duration}\`\n` +
          `• **Requested by:** <@${interaction.user.id}> • ${source}\n\n` +
          `▶ **Currently Playing:** ${currentPlayingText}`
        )
        .setThumbnail(track.thumbnail && /^https:\/\//i.test(track.thumbnail) ? track.thumbnail : BRAND_LOGO_URL)
        .setFooter({ text: `${BRAND_NAME} • ${result.queue.size} track(s) waiting in queue`, iconURL: BRAND_LOGO_URL })
        .setTimestamp();

      const queueRow = new ActionRowBuilder().addComponents(
        new ButtonBuilder()
          .setCustomId(BUTTON_IDS.QUEUE)
          .setStyle(ButtonStyle.Secondary)
          .setEmoji(getButtonEmoji(EMOJIS.queue, '📜'))
          .setLabel('View Queue'),
        new ButtonBuilder()
          .setCustomId(BUTTON_IDS.LIKE)
          .setStyle(ButtonStyle.Secondary)
          .setEmoji(getButtonEmoji(EMOJIS.heart, '💖'))
          .setLabel('Favorite')
      );

      await interaction.editReply({ embeds: [embed], components: [queueRow] });
      void refreshNowPlayingMessage(result.queue);
    } catch (error) {
      console.error('[Search Selection Error]', error);
      await interaction.editReply({
        embeds: [
          createNotificationEmbed(
            `${EMOJIS.refused} Could Not Play Track`,
            `${error.message || error}`,
            ERROR_COLOR
          )
        ]
      });
    }
    return;
  }

  if (!Object.values(BUTTON_IDS).includes(interaction.customId)) return;

  if (!interaction.inGuild()) {
    await safeReplyEmbed(interaction, `${EMOJIS.refused} Server Only`, 'These controls only work in servers.', ERROR_COLOR, true);
    return;
  }

  const queue = getQueue(interaction.guildId);
  if (!queue || !hasActiveTrack(queue)) {
    await safeReplyEmbed(interaction, `${EMOJIS.warning} Nothing Playing`, 'Nothing is currently playing.', BRAND_COLOR, true);
    return;
  }

  const allowed = await ensureSameVoiceChannel(interaction, queue);
  if (!allowed) return;

  try {
    if (interaction.customId === BUTTON_IDS.PAUSE_RESUME) {
      if (queue.node.isPaused()) {
        queue.node.resume();
        await safeReplyEmbed(interaction, `${EMOJIS.play} Playback Resumed`, 'Music playback has been resumed.', SUCCESS_COLOR, true);
      } else {
        queue.node.pause();
        await safeReplyEmbed(interaction, `${EMOJIS.pause} Playback Paused`, 'Music playback has been paused.', BRAND_COLOR, true);
      }

      await refreshNowPlayingMessage(queue);
      return;
    }

    if (interaction.customId === BUTTON_IDS.PREVIOUS) {
      if (!queue.history.previousTrack) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} No History`, 'There is no previous track in listening history.', BRAND_COLOR, true);
        return;
      }

      await queue.history.previous();
      await safeReplyEmbed(interaction, `${EMOJIS.previous} Previous Track`, 'Jumped back to previous track in history.', SUCCESS_COLOR, true);
      return;
    }

    if (interaction.customId === BUTTON_IDS.SKIP) {
      const skipped = queue.node.skip();
      if (skipped) {
        await safeReplyEmbed(interaction, `${EMOJIS.skip} Track Skipped`, 'Skipped current track.', SUCCESS_COLOR, true);
      } else {
        await safeReplyEmbed(interaction, `${EMOJIS.refused} Skip Failed`, 'Could not skip current track.', ERROR_COLOR, true);
      }
      return;
    }

    if (interaction.customId === BUTTON_IDS.STOP) {
      disableContinuousPlayback(interaction.guildId, queue);
      queue.node.stop();
      await safeReplyEmbed(interaction, `${EMOJIS.stop} Playback Stopped`, 'Stopped music playback and cleared active audio.', BRAND_COLOR, true);
      return;
    }

    if (interaction.customId === BUTTON_IDS.QUEUE) {
      if (!hasActiveTrack(queue)) {
        await safeReplyEmbed(interaction, `${EMOJIS.queue} Queue is Empty`, 'No tracks are currently queued.', BRAND_COLOR, true);
        return;
      }

      await safeReply(interaction, {
        embeds: [buildQueueEmbed(queue)],
        flags: MessageFlags.Ephemeral,
      });
      return;
    }

    if (interaction.customId === BUTTON_IDS.LIKE) {
      const currentTrack = queue.currentTrack;
      if (!currentTrack) {
        await safeReplyEmbed(interaction, `${EMOJIS.warning} Nothing Playing`, 'No active track to like.', BRAND_COLOR, true);
        return;
      }

      const result = saveTrackToFavorites(interaction.user.id, currentTrack);
      if (result.added) {
        musicTaste.recordTrack(interaction.guildId, interaction.user.id, currentTrack, 3, 'like');
        await safeReplyEmbed(
          interaction,
          `${EMOJIS.heart} Added to Favorites`,
          `Saved **${result.track.title}** to your favorites playlist.\nTotal favorites: **${result.total}**\n\nUse \`/playlist play\` to listen anytime!`,
          SUCCESS_COLOR,
          true
        );
      } else {
        await safeReplyEmbed(
          interaction,
          `${EMOJIS.heart} Already in Favorites`,
          `**${result.track.title}** is already in your favorites playlist.`,
          BRAND_COLOR,
          true
        );
      }
      return;
    }

    if (interaction.customId === BUTTON_IDS.PLAYLIST) {
      const favorites = getUserFavorites(interaction.user.id);
      await safeReply(interaction, {
        embeds: [buildFavoritesEmbed(interaction.user, favorites)],
        flags: MessageFlags.Ephemeral,
      });
      return;
    }
  } catch (error) {
    console.error('[Button Error]', error);
    await safeReplyEmbed(interaction, `${EMOJIS.refused} Button Error`, `${error.message || error}`, ERROR_COLOR, true);
  }
}

async function registerSlashCommands() {
  if (!CLIENT_ID) {
    console.warn('[Slash Commands] DISCORD_CLIENT_ID is missing; skipping slash command registration.');
    return;
  }

  const platformChoices = [
    { name: 'Auto', value: 'auto' },
    { name: 'YouTube', value: 'youtube' },
    { name: 'YouTube Music', value: 'youtubemusic' },
    { name: 'Spotify', value: 'spotify' },
    { name: 'Apple Music', value: 'applemusic' },
    { name: 'SoundCloud', value: 'soundcloud' },
    { name: 'Deezer', value: 'deezer' },
    { name: 'TIDAL', value: 'tidal' },
  ];

  const commands = [
    new SlashCommandBuilder()
      .setName('play')
      .setDescription('Plays a track from a url or search term')
      .addStringOption((option) =>
        option
          .setName('query')
          .setDescription('Song name or link')
          .setRequired(true)
          .setAutocomplete(true),
      )
      .addStringOption((option) =>
        option
          .setName('platform')
          .setDescription('Preferred source')
          .setRequired(false)
          .addChoices(...platformChoices),
      )
      .addBooleanOption((option) =>
        option
          .setName('strict')
          .setDescription('Prefer exact song-title matches'),
      ),

    new SlashCommandBuilder()
      .setName('search')
      .setDescription('Search tracks from supported platforms')
      .addStringOption((option) =>
        option
          .setName('query')
          .setDescription('Song name')
          .setRequired(true)
          .setAutocomplete(true),
      )
      .addStringOption((option) =>
        option
          .setName('platform')
          .setDescription('Preferred source')
          .setRequired(false)
          .addChoices(...platformChoices),
      )
      .addBooleanOption((option) =>
        option
          .setName('strict')
          .setDescription('Prefer exact song-title matches'),
      ),

    new SlashCommandBuilder()
      .setName('strict')
      .setDescription('Toggle strict song match mode for this server')
      .addStringOption((option) =>
        option
          .setName('mode')
          .setDescription('Strict mode state')
          .setRequired(true)
          .addChoices({ name: 'on', value: 'on' }, { name: 'off', value: 'off' }),
      ),

    new SlashCommandBuilder()
      .setName('queue')
      .setDescription('Queue actions')
      .addSubcommand((sub) => sub.setName('list').setDescription('Shows the current queue for this server'))
      .addSubcommand((sub) => sub.setName('clear').setDescription('Clears all upcoming tracks in queue')),

    new SlashCommandBuilder().setName('invite').setDescription('Get a link to add SyncInk Radio to another server'),

    new SlashCommandBuilder().setName('shuffle').setDescription('Shuffle the queue'),

    new SlashCommandBuilder()
      .setName('loop')
      .setDescription('Set loop mode')
      .addStringOption((option) =>
        option
          .setName('mode')
          .setDescription('Loop mode')
          .setRequired(true)
          .addChoices(
            { name: 'all', value: 'all' },
            { name: 'current', value: 'current' },
            { name: 'disable', value: 'disable' },
          ),
      ),

    new SlashCommandBuilder()
      .setName('skip')
      .setDescription('Skip to the next track or multiple tracks')
      .addIntegerOption((option) =>
        option
          .setName('count')
          .setDescription('How many tracks to skip (default: 1)')
          .setRequired(false)
          .setMinValue(1)
          .setMaxValue(10),
      ),

    new SlashCommandBuilder()
      .setName('volume')
      .setDescription('Adjust playback volume')
      .addIntegerOption((option) =>
        option
          .setName('percent')
          .setDescription('0 to 200')
          .setRequired(true)
          .setMinValue(0)
          .setMaxValue(200),
      ),

    new SlashCommandBuilder().setName('np').setDescription('Show information about the currently playing track'),

    new SlashCommandBuilder()
      .setName('remove')
      .setDescription('Removes a track from queue by position')
      .addIntegerOption((option) =>
        option
          .setName('position')
          .setDescription('Track number from /queue list')
          .setRequired(true)
          .setMinValue(1),
      ),

    new SlashCommandBuilder().setName('help').setDescription('Lists all commands'),

    new SlashCommandBuilder()
      .setName('taste')
      .setDescription('Manage your private music taste profile and personalized autoplay')
      .addStringOption((option) =>
        option
          .setName('mode')
          .setDescription('Enable, pause, inspect, or erase your music taste profile')
          .setRequired(true)
          .addChoices(
            { name: 'Enable learning', value: 'on' },
            { name: 'Pause learning', value: 'off' },
            { name: 'Show status', value: 'status' },
            { name: 'Erase profile', value: 'forget' },
          ),
      ),

    new SlashCommandBuilder()
      .setName('lyrics')
      .setDescription('Searches a track lyrics')
      .addStringOption((option) =>
        option
          .setName('query')
          .setDescription('Optional: song title. Uses current track if omitted')
          .setRequired(false),
      ),

    new SlashCommandBuilder()
      .setName('autoplay')
      .setDescription('Enable or disable autoplay')
      .addStringOption((option) =>
        option
          .setName('mode')
          .setDescription('Autoplay mode')
          .setRequired(true)
          .addChoices({ name: 'on', value: 'on' }, { name: 'off', value: 'off' }),
      ),

    new SlashCommandBuilder().setName('pause').setDescription('Pauses playback'),

    new SlashCommandBuilder().setName('resume').setDescription('Resumes playback'),

    new SlashCommandBuilder().setName('replay').setDescription('Replay the current track from start'),

    new SlashCommandBuilder()
      .setName('bassboost')
      .setDescription('Changes bassboost filter settings')
      .addStringOption((option) =>
        option
          .setName('mode')
          .setDescription('Bassboost profile')
          .setRequired(true)
          .addChoices(
            { name: 'off', value: 'off' },
            { name: 'low', value: 'low' },
            { name: 'normal', value: 'normal' },
            { name: 'high', value: 'high' },
          ),
      ),

    new SlashCommandBuilder()
      .setName('8d')
      .setDescription('Toggle 8D filter')
      .addStringOption((option) =>
        option
          .setName('mode')
          .setDescription('8D mode')
          .setRequired(true)
          .addChoices({ name: 'on', value: 'on' }, { name: 'off', value: 'off' }),
      ),

    new SlashCommandBuilder()
      .setName('seek')
      .setDescription('Seek to a specific time in current track')
      .addStringOption((option) =>
        option
          .setName('position')
          .setDescription('Examples: 90, 1:30, 00:01:30, 2m')
          .setRequired(true),
      ),

    new SlashCommandBuilder().setName('previous').setDescription('Go back to previous track in listening history'),

    new SlashCommandBuilder().setName('stop').setDescription('Stop playback'),

    new SlashCommandBuilder().setName('leave').setDescription('Disconnect from voice channel'),

    new SlashCommandBuilder()
      .setName('playlist')
      .setDescription('Manage your liked playlist')
      .addSubcommand((subcommand) => subcommand.setName('show').setDescription('Show your liked tracks'))
      .addSubcommand((subcommand) => subcommand.setName('play').setDescription('Play your liked tracks'))
      .addSubcommand((subcommand) =>
        subcommand
          .setName('remove')
          .setDescription('Remove a liked track by number')
          .addIntegerOption((option) =>
            option
              .setName('track')
              .setDescription('Track number from /playlist show')
              .setRequired(true)
              .setMinValue(1),
          ),
      )
      .addSubcommand((subcommand) => subcommand.setName('clear').setDescription('Clear your liked playlist')),

    new SlashCommandBuilder()
      .setName('radio')
      .setDescription('Start a continuously rotating themed music station')
      .addStringOption((option) =>
        option
          .setName('station')
          .setDescription('Choose a music style for fresh track rotation')
          .setRequired(true)
          .addChoices(
            { name: '☕ Lofi Girl (Relax/Study Beats)', value: 'lofi' },
            { name: '🌆 Synthwave / Retro Chill', value: 'synthwave' },
            { name: '🎷 Coffee Shop Jazz & Piano', value: 'coffee' },
            { name: '🌙 Deep Sleep & Ambient Calm', value: 'sleep' },
            { name: '⚡ NCS Gaming & EDM Beats', value: 'gaming' },
          ),
      ),

    new SlashCommandBuilder()
      .setName('lofi')
      .setDescription('Start continuous 24/7 Lofi beats stream instantly'),

    new SlashCommandBuilder()
      .setName('247')
      .setDescription('Toggle 24/7 mode (stays in voice channel until everyone leaves)')
      .addStringOption((option) =>
        option
          .setName('mode')
          .setDescription('Enable or disable 24/7 mode')
          .setRequired(true)
          .addChoices({ name: 'on', value: 'on' }, { name: 'off', value: 'off' }),
      ),

    new SlashCommandBuilder()
      .setName('filter')
      .setDescription('Apply audio sound filter effects')
      .addStringOption((option) =>
        option
          .setName('type')
          .setDescription('Filter effect type')
          .setRequired(true)
          .addChoices(
            { name: '✨ Reset / Turn Off', value: 'off' },
            { name: '🎧 Nightcore (Speed + Pitch)', value: 'nightcore' },
            { name: '🌊 Vaporwave (Slowed + Reverb)', value: 'vaporwave' },
            { name: '🔊 Bassboost (Normal)', value: 'bassboost' },
            { name: '💥 Bassboost (High)', value: 'bassboost_high' },
            { name: '🌀 8D Audio Surround', value: '8D' },
            { name: '🎤 Karaoke (Vocal Suppression)', value: 'karaoke' },
            { name: '🎚️ Dynamic Normalizer', value: 'normalizer' },
          ),
      ),
    new SlashCommandBuilder()
      .setName('update')
      .setDescription('Pull latest updates directly from GitHub and restart the bot')
      .setDefaultMemberPermissions(PermissionFlagsBits.Administrator),
  ].map((command) => command.toJSON());

  const rest = new REST({ version: '10' }).setToken(TOKEN);

  await rest.put(Routes.applicationCommands(CLIENT_ID), { body: commands });
  console.log('[Slash Commands] Registered globally (can take up to 1 hour to appear).');
  if (GUILD_ID) {
    await rest.put(Routes.applicationGuildCommands(CLIENT_ID, GUILD_ID), { body: commands });
    console.log(`[Slash Commands] Also registered immediately to guild ${GUILD_ID}.`);
  }
}

player.events.on('playerStart', async (queue, track) => {
  const channel = queue.metadata?.textChannel;
  if (!channel || typeof channel.send !== 'function') return;
  lastTrackStartTimes.set(queue.guild.id, Date.now());

  const stationId = radioStationsByGuild.get(queue.guild.id) || queue.metadata?.radioStationId;
  if (stationId && queue.tracks.toArray().length <= 3) {
    void refillRadioQueue(queue, stationId).catch((error) => {
      console.error('[Radio Prefetch Error]', error);
    });
  }

  const requesterId = track?.requestedBy?.id;
  if (requesterId && queue.repeatMode === QueueRepeatMode.AUTOPLAY && musicTaste.getProfile(queue.guild.id, requesterId)?.enabled) {
    const historyUrls = queue.history.tracks.map((item) => item.url).filter(Boolean);
    const historySongKeys = new Set(queue.history.tracks.map(canonicalSongKey).filter(Boolean));
    void musicTaste.prefetchAutoplay({
      guildId: queue.guild.id,
      userId: requesterId,
      currentTrack: track,
      history: queue.history,
      historyUrls,
      historySongKeys,
    }).catch((error) => {
      console.error('[Taste Prefetch Error]', error);
    });
  }

  try {
    const existing = nowPlayingRegistry.get(queue.guild.id);
    if (existing) {
      const storedChannel = await client.channels.fetch(existing.channelId).catch(() => null);
      if (storedChannel && storedChannel.isTextBased()) {
        const storedMessage = await storedChannel.messages.fetch(existing.messageId).catch(() => null);
        if (storedMessage) {
          await sendOrEditNowPlaying(storedMessage, queue, track);
          return;
        }
      }
    }

    await sendOrEditNowPlaying(channel, queue, track);
  } catch (err) {
    console.error('[playerStart send error]', err);
  }
});

player.events.on('playerPause', async (queue) => {
  await refreshNowPlayingMessage(queue);
});

player.events.on('playerResume', async (queue) => {
  await refreshNowPlayingMessage(queue);
});

player.events.on('playerSkip', async (queue, track, reason, description) => {
  console.log(`[Player Skip] Track: ${track?.title}, Reason: ${reason}, Desc: ${description}`);
  await refreshNowPlayingMessage(queue);
});

player.events.on('willAutoPlay', async (queue, tracks, done) => {
  let completed = false;
  const finish = (track) => {
    if (completed) return;
    completed = true;
    done(track || null);
  };

  try {
    const anchor = queue.history.tracks.at(-1) || queue.currentTrack;
    const historyUrls = queue.history.tracks.map((track) => track.url).filter(Boolean);
    const historySongKeys = new Set(queue.history.tracks.map(canonicalSongKey).filter(Boolean));
    const userId = anchor?.requestedBy?.id;
    const cachedTrack = musicTaste.takePrefetched({
      guildId: queue.guild.id,
      userId,
      currentTrack: anchor,
      historyUrls,
      historySongKeys,
    });
    const nextTrack = cachedTrack || await musicTaste.chooseAutoplay({
      guildId: queue.guild.id,
      userId,
      currentTrack: anchor,
      candidates: tracks,
      historyUrls,
      historySongKeys,
      allowAI: false,
    });
    finish(nextTrack);
  } catch (error) {
    console.error('[Taste Autoplay Error]', error);
    const historyKeys = new Set(queue.history.tracks.map(canonicalSongKey).filter(Boolean));
    finish(tracks.find((track) => track?.url && !isUnrequestedVariant(track) && !queue.history.tracks.find((played) => played.url === track.url) && !historyKeys.has(canonicalSongKey(track))));
  }
});

player.events.on('playerFinish', async (queue, track) => {
  const expectedMs = Number(track?.durationMS || 0);
  const startTime = lastTrackStartTimes.get(queue.guild.id) || 0;
  const playtime = Number(queue.node.streamTime || (startTime ? Date.now() - startTime : 0));
  if (playtime < 1500 && expectedMs > 5000) {
    console.log(`[Stream Warning] Track ended unusually early at ${playtime}ms (expected ${expectedMs}ms)`);
  }
  const requestedBy = track?.requestedBy?.id;
  const listenedEnough = expectedMs > 0 && playtime >= expectedMs * 0.6;
  if (listenedEnough && requestedBy && !queue.metadata?.radioStationId) {
    musicTaste.recordTrack(queue.guild.id, requestedBy, track, 0.5, 'play');
  }
});



player.events.on('emptyQueue', async (queue) => {
  const channel = queue.metadata?.textChannel;
  const guildId = queue.guild.id;

  // Radio sessions refill with fresh tracks from their selected genre rather than looping one stream.
  const radioStationId = radioStationsByGuild.get(guildId) || queue.metadata?.radioStationId;
  if (radioStationId) {
    try {
      if (await refillRadioQueue(queue, radioStationId)) return;
    } catch (err) {
      console.error('[Radio Refill Error]', err);
    }
  }

  // 24/7 keeps regular queues alive through related-track discovery. Radio queues use their genre station above.
  if (twentyFourSevenGuilds.has(guildId) && queue.repeatMode === QueueRepeatMode.OFF) {
    queue.setRepeatMode(QueueRepeatMode.AUTOPLAY);
  }

  // 2. Custom Autoplay: If autoplay mode is enabled or last track had history, find next related song
  if (queue.repeatMode === QueueRepeatMode.AUTOPLAY) {
    try {
      const lastTrack = queue.history.tracks.at(-1) || queue.currentTrack;
      if (lastTrack) {
        console.log(`[Autoplay] Looking for related recommendations for "${lastTrack.title}"...`);
        const artist = String(lastTrack.author || '').trim();
        const title = String(lastTrack.cleanTitle || lastTrack.title || '').trim();
        const queries = [`${artist} songs similar to ${title}`, `${artist} official audio`, `${title} similar songs`].filter(Boolean);
        const playedUrls = new Set(queue.history.tracks.map((item) => item.url).filter(Boolean));
        const playedSongKeys = new Set(queue.history.tracks.map(canonicalSongKey).filter(Boolean));
        let nextTrack = null;
        for (const query of queries) {
          const res = await runSearch(query, 'auto', client.user);
          nextTrack = res.tracks.find((item) => item?.url && !isUnrequestedVariant(item, query) && !playedUrls.has(item.url) && !playedSongKeys.has(canonicalSongKey(item)));
          if (nextTrack) break;
        }
        if (nextTrack) {
          queue.addTrack(nextTrack);
          if (!queue.isPlaying()) queue.node.play();
          if (channel && typeof channel.send === 'function') {
            const autoEmbed = createNotificationEmbed(
              '📻 Autoplay: Next Up',
              `Picked **[${nextTrack.title}](${nextTrack.url})** from a fresh recommendation.`,
              SUCCESS_COLOR,
            );
            channel.send({ embeds: [autoEmbed] }).catch(() => null);
          }
          return;
        }
      }
    } catch (autoErr) {
      console.error('[Autoplay Error]', autoErr);
    }
  }

  if (!channel || typeof channel.send !== 'function') return;

  const startedAt = lastTrackStartTimes.get(guildId) || 0;
  if (startedAt > 0 && Date.now() - startedAt < 4_000) {
    return;
  }

  if (!canSendGuildMessage(guildId, 'emptyQueue', 120_000)) return;
  const embed = createNotificationEmbed('🏁 Queue Finished', 'All songs have finished playing. Use `/play` or `/lofi` to start another session!', BRAND_COLOR);
  channel.send({ embeds: [embed] }).catch(() => null);
});

player.events.on('error', (queue, error) => {
  console.error('[Queue Error]', error);
});

player.events.on('playerError', async (queue, error, track) => {
  console.error('[Player Error]', error, track?.title || track?.cleanTitle || 'unknown track');

  try {
    if (isStreamErrorRecoverable(error)) {
      await recoverTrackFromStreamFailure(queue, track);
    }
  } catch (recoveryError) {
    console.error('[Recovery Error]', recoveryError);
  }
});

client.on(Events.InteractionCreate, async (interaction) => {
  const handledAutocomplete = await handleAutocomplete(interaction);
  if (handledAutocomplete) return;

  await handleCommandInteraction(interaction);
  await handleButtonInteraction(interaction);
});

client.on(Events.VoiceStateUpdate, (oldState, newState) => {
  const guild = oldState.guild || newState.guild;
  if (!guild) return;

  const queue = getQueue(guild.id);
  if (!queue || !queue.channel) return;

  const botVoiceChannel = queue.channel;

  // Check if this update relates to the bot's channel
  const inBotChannel = oldState.channelId === botVoiceChannel.id || newState.channelId === botVoiceChannel.id;
  if (!inBotChannel) return;

  // Calculate non-bot human members in the voice channel
  const humanMembers = botVoiceChannel.members.filter((m) => !m.user.bot);

  if (humanMembers.size === 0) {
    if (twentyFourSevenGuilds.has(guild.id) || radioStationsByGuild.has(guild.id)) {
      if (emptyVcTimers.has(guild.id)) {
        clearTimeout(emptyVcTimers.get(guild.id));
        emptyVcTimers.delete(guild.id);
      }
      return;
    }

    // Only bot(s) left in the voice channel
    if (!emptyVcTimers.has(guild.id)) {
      console.log(`[Auto-Leave] Voice channel empty in guild ${guild.id}. Disconnecting in 30 seconds...`);
      const timer = setTimeout(() => {
        emptyVcTimers.delete(guild.id);
        const currentQueue = getQueue(guild.id);
        if (currentQueue && currentQueue.channel) {
          const currentHumans = currentQueue.channel.members.filter((m) => !m.user.bot);
          if (currentHumans.size === 0) {
            console.log(`[Auto-Leave] Left voice channel in guild ${guild.id} because it remained empty.`);
            const textChannel = currentQueue.metadata?.textChannel;
            if (textChannel && typeof textChannel.send === 'function') {
              textChannel.send('👋 Disconnected from voice channel because everyone left.').catch(() => null);
            }
            disableContinuousPlayback(guild.id, currentQueue);
            currentQueue.delete();
            nowPlayingRegistry.delete(guild.id);
          }
        }
      }, 30_000);
      emptyVcTimers.set(guild.id, timer);
    }
  } else {
    // Someone is in the channel, cancel any pending leave timer
    if (emptyVcTimers.has(guild.id)) {
      console.log(`[Auto-Leave] User joined voice channel in guild ${guild.id}. Cancelled auto-disconnect timer.`);
      clearTimeout(emptyVcTimers.get(guild.id));
      emptyVcTimers.delete(guild.id);
    }
  }
});

client.once(Events.ClientReady, async (readyClient) => {
  console.log(`Logged in as ${readyClient.user.tag}`);
  console.log(`[Startup] FFmpeg path: ${resolvedFFmpegPath || 'auto-detect'}`);
  console.log(`[Startup] Direct YTDL stream fallback: ${ENABLE_DIRECT_YTDL_STREAM ? 'enabled' : 'disabled'}`);
  console.log(`[Audio Engine] Available Opus encoder: ${probeOpusEngine()}`);
  try {
    const extractorIds = Array.from(player.extractors.store.keys?.() || []);
    console.log(`[Startup] Extractors loaded: ${extractorIds.join(', ') || 'none'}`);
    console.log(`[Startup] YouTube extractor active: ${isYoutubeiReady}`);
  } catch {
    // no-op
  }

  try {
    const depsReport = player.scanDeps();
    console.log(depsReport);

    const hasOpusRuntime =
      /-\s+mediaplex:\s*(?!N\/A)/i.test(depsReport) ||
      /-\s+@discordjs\/opus:\s*(?!N\/A)/i.test(depsReport) ||
      /-\s+@evan\/opus:\s*(?!N\/A)/i.test(depsReport) ||
      /-\s+opusscript:\s*(?!N\/A)/i.test(depsReport) ||
      /-\s+node-opus:\s*(?!N\/A)/i.test(depsReport);
    if (!hasOpusRuntime) {
      console.warn('[Startup] Warning: Opus support appears unavailable. Install opusscript/@discordjs/opus or verify ffmpeg/libopus.');
    }
  } catch (scanError) {
    console.warn('[Startup] Dependency scan failed:', scanError?.message || scanError);
  }

  try {
    await registerSlashCommands();
  } catch (error) {
    console.error('[Slash Command Registration Error]', error);
  }
});

function startHealthServer() {
  const server = http.createServer((_, res) => {
    res.statusCode = 200;
    res.setHeader('Content-Type', 'application/json');
    res.end(
      JSON.stringify({
        ok: true,
        service: 'syncink-radio',
        audio: {
          opusEncoder: opusRuntime?.OpusEncoder?.type || 'not initialized',
          eventLoopDelayP95Ms: Number((eventLoopDelay.percentile(95) / 1e6).toFixed(1)),
          activeQueues: player.nodes.cache.size,
        },
      }),
    );
    eventLoopDelay.reset();
  });

  server.listen(PORT, () => {
    console.log(`[Health] HTTP server listening on ${PORT}`);
  });

  return server;
}

let healthServer;

async function shutdown(signal) {
  console.log(`[Shutdown] Received ${signal}. Closing gracefully...`);

  try {
    if (healthServer) {
      healthServer.close();
    }

    for (const queue of player) {
      queue.delete();
    }

    await client.destroy();
  } catch (error) {
    console.error('[Shutdown Error]', error);
  } finally {
    process.exit(0);
  }
}

async function bootstrap() {
  ensureFavoritesStore();
  healthServer = startHealthServer();

  await player.extractors.loadMulti(DefaultExtractors);
  if (YoutubeiExtractor) {
    try {
      await player.extractors.register(YoutubeiExtractor, {
        ignoreSignInErrors: true,
        useYoutubeDL: true,
        streamOptions: {
          useClient: 'IOS',
          highWaterMark: 1024 * 1024 * 16, // 16MB cap keeps buffering useful without wasting phone RAM
        },
      });

      const loadedExtractorIds = Array.from(player.extractors.store.keys?.() || []);
      isYoutubeiReady = loadedExtractorIds.includes(YOUTUBEI_EXTRACTOR_ID);

      if (isYoutubeiReady) {
        console.log('[Startup] YouTube extractor registered (discord-player-youtubei).');
      } else {
        console.warn('[Startup] YouTube extractor register call completed, but extractor is not active.');
      }
    } catch (error) {
      isYoutubeiReady = false;
      console.warn('[Startup] YouTube extractor failed to initialize:', error?.message || error);
    }
  } else {
    isYoutubeiReady = false;
    console.warn('[Startup] YouTube extractor package not found. YouTube links/search may fail.');
  }
  await client.login(TOKEN);
}

process.on('SIGTERM', () => {
  void shutdown('SIGTERM');
});

process.on('SIGINT', () => {
  void shutdown('SIGINT');
});

process.on('unhandledRejection', (reason) => {
  console.error('[Unhandled Rejection]', reason);
});

process.on('uncaughtException', (error) => {
  console.error('[Uncaught Exception]', error);
});

player.on('debug', (message) => {
  if (process.env.PLAYER_DEBUG === 'true') {
    console.log(`[Player Debug] ${message}`);
  }
});

player.events.on('debug', (queue, message) => {
  if (process.env.PLAYER_DEBUG === 'true') {
    console.log(`[Queue Debug][${queue.guild.id}] ${message}`);
  }
});

bootstrap().catch((error) => {
  console.error('[Startup Error]', error);
  process.exit(1);
});









