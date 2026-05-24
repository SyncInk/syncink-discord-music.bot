'use strict';

require('dotenv').config();

const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
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
} = require('discord.js');
const { Player, QueueRepeatMode, QueryType, QueryResolver } = require('discord-player');
const { DefaultExtractors } = require('@discord-player/extractor');
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

const BRAND_NAME = 'SyncInk Radio';
const BRAND_COLOR = 0x1f8bff;
const SUCCESS_COLOR = 0x2ecc71;
const WARNING_COLOR = 0xf1c40f;
const ERROR_COLOR = 0xe74c3c;

const MAX_QUEUE_PREVIEW = 10;
const MAX_PLAYLIST_LOAD = 25;
const MAX_AUTOCOMPLETE_CHOICES = 10;

const BUTTON_IDS = {
  PAUSE_RESUME: 'syncink_pause_resume',
  SKIP: 'syncink_skip',
  STOP: 'syncink_stop',
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

const CLIENT_ID =
  normalizeSnowflake(process.env.DISCORD_CLIENT_ID) ||
  normalizeSnowflake(process.env.CLIENT_ID) ||
  inferClientIdFromToken(TOKEN) ||
  null;

const GUILD_ID = normalizeSnowflake(process.env.DISCORD_GUILD_ID) || normalizeSnowflake(process.env.GUILD_ID) || null;
const PORT = Number(process.env.PORT || 3000);
const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, 'data');
const FAVORITES_PATH = path.join(DATA_DIR, 'favorites.json');
const DEFAULT_AUTOPLAY = toBoolean(process.env.DEFAULT_AUTOPLAY, false);

if (!TOKEN) {
  throw new Error('Missing DISCORD_TOKEN in .env');
}

const PLATFORM_CONFIG = {
  auto: {
    label: 'Auto',
    searchEngine: QueryType.AUTO_SEARCH,
    decorateQuery(query) {
      return query;
    },
  },
  youtube: {
    label: 'YouTube',
    searchEngine: QueryType.YOUTUBE_SEARCH,
    decorateQuery(query) {
      return query;
    },
  },
  youtubemusic: {
    label: 'YouTube Music',
    searchEngine: QueryType.YOUTUBE_SEARCH,
    decorateQuery(query) {
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
  soundcloud: 'SoundCloud',
  spotify: 'Spotify',
  apple_music: 'Apple Music',
  arbitrary: 'Direct',
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
  connectionTimeout: 15_000,
  lagMonitor: 60_000,
});

const nowPlayingRegistry = new Map();
const guildMessageCooldowns = new Map();
const playCommandCooldowns = new Map();
const lastTrackStartTimes = new Map();

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

function renderProgressBar(progress, size = 16) {
  const safeProgress = Number.isFinite(progress) ? Math.max(0, Math.min(100, progress)) : 0;
  const filled = Math.round((safeProgress / 100) * size);
  const empty = size - filled;
  return `[${'='.repeat(filled)}${'-'.repeat(empty)}] ${Math.round(safeProgress)}%`;
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

function uniqueQueryTypes(queryTypes) {
  const unique = [];
  for (const type of queryTypes) {
    if (!type || unique.includes(type)) continue;
    unique.push(type);
  }
  return unique;
}

function buildSearchEngineCandidates(platform, resolvedType, looksLikeUrl) {
  if (looksLikeUrl) {
    const urlSpecific = [
      QueryType.YOUTUBE_VIDEO,
      QueryType.YOUTUBE_PLAYLIST,
      QueryType.YOUTUBE,
      QueryType.SOUNDCLOUD_TRACK,
      QueryType.SOUNDCLOUD_PLAYLIST,
      QueryType.SOUNDCLOUD,
      QueryType.SPOTIFY_SONG,
      QueryType.SPOTIFY_ALBUM,
      QueryType.SPOTIFY_PLAYLIST,
      QueryType.APPLE_MUSIC_SONG,
      QueryType.APPLE_MUSIC_ALBUM,
      QueryType.APPLE_MUSIC_PLAYLIST,
    ];

    if (urlSpecific.includes(resolvedType)) {
      return uniqueQueryTypes([resolvedType, QueryType.AUTO_SEARCH, QueryType.YOUTUBE_SEARCH, QueryType.SOUNDCLOUD_SEARCH]);
    }

    return uniqueQueryTypes([resolvedType, QueryType.AUTO_SEARCH, QueryType.YOUTUBE_SEARCH, QueryType.SOUNDCLOUD_SEARCH]);
  }

  if (platform === 'youtube') {
    return uniqueQueryTypes([QueryType.YOUTUBE_SEARCH, QueryType.AUTO_SEARCH, QueryType.SOUNDCLOUD_SEARCH]);
  }

  if (platform === 'youtubemusic') {
    return uniqueQueryTypes([QueryType.YOUTUBE_SEARCH, QueryType.AUTO_SEARCH]);
  }

  if (platform === 'soundcloud') {
    return uniqueQueryTypes([QueryType.SOUNDCLOUD_SEARCH, QueryType.YOUTUBE_SEARCH, QueryType.AUTO_SEARCH]);
  }

  if (platform === 'spotify') {
    return uniqueQueryTypes([QueryType.SPOTIFY_SEARCH, QueryType.YOUTUBE_SEARCH, QueryType.AUTO_SEARCH]);
  }

  if (platform === 'applemusic') {
    return uniqueQueryTypes([QueryType.APPLE_MUSIC_SEARCH, QueryType.YOUTUBE_SEARCH, QueryType.AUTO_SEARCH]);
  }

  if (platform === 'deezer' || platform === 'tidal') {
    return uniqueQueryTypes([QueryType.AUTO_SEARCH, QueryType.YOUTUBE_SEARCH, QueryType.SOUNDCLOUD_SEARCH]);
  }

  return uniqueQueryTypes([QueryType.YOUTUBE_SEARCH, QueryType.AUTO_SEARCH, QueryType.SOUNDCLOUD_SEARCH]);
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

  const searchEngines = buildSearchEngineCandidates(selectedPlatform, resolvedType, normalized.looksLikeUrl);

  return {
    query: resolved?.query || preparedQuery,
    searchEngines,
    primarySearchEngine: searchEngines[0] || QueryType.AUTO_SEARCH,
    fallbackSearchEngine: QueryType.YOUTUBE_SEARCH,
    label: config.label,
    looksLikeUrl: normalized.looksLikeUrl,
    resolvedType,
    selectedPlatform,
  };
}

function getSourceLabel(track) {
  return SOURCE_LABELS[track?.source] || String(track?.source || 'Unknown');
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

function prioritizeTracksForPlayback(tracks) {
  if (!Array.isArray(tracks) || tracks.length <= 1) return tracks;

  const sourceScore = {
    youtube: 5,
    arbitrary: 4,
    soundcloud: 3,
    spotify: 2,
    apple_music: 2,
  };

  return [...tracks].sort((a, b) => {
    const aScore = sourceScore[a?.source] ?? 1;
    const bScore = sourceScore[b?.source] ?? 1;
    return bScore - aScore;
  });
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

function hasActiveTrack(queue) {
  return Boolean(queue && queue.currentTrack);
}

function buildControlsRow() {
  return new ActionRowBuilder().addComponents(
    new ButtonBuilder().setCustomId(BUTTON_IDS.PAUSE_RESUME).setStyle(ButtonStyle.Primary).setLabel('Pause/Resume'),
    new ButtonBuilder().setCustomId(BUTTON_IDS.SKIP).setStyle(ButtonStyle.Secondary).setLabel('Skip'),
    new ButtonBuilder().setCustomId(BUTTON_IDS.STOP).setStyle(ButtonStyle.Danger).setLabel('Stop'),
    new ButtonBuilder().setCustomId(BUTTON_IDS.LIKE).setStyle(ButtonStyle.Success).setLabel('Like'),
    new ButtonBuilder().setCustomId(BUTTON_IDS.PLAYLIST).setStyle(ButtonStyle.Secondary).setLabel('Playlist'),
  );
}

function buildNowPlayingEmbed(queue, track) {
  const current = track || queue?.currentTrack;

  if (!current) {
    return new EmbedBuilder()
      .setColor(BRAND_COLOR)
      .setTitle(`${BRAND_NAME} - Now Playing`)
      .setDescription('Nothing is currently playing.');
  }

  const timestamp = queue?.node?.getTimestamp?.();
  const progressLine = timestamp
    ? `${renderProgressBar(timestamp.progress)}\n${timestamp.current.label}/${timestamp.total.label}`
    : 'Progress unavailable';

  const queueSize = queue?.size ?? 0;
  const requestedBy = current.requestedBy ? `<@${current.requestedBy.id}>` : 'Unknown';
  const source = getSourceLabel(current);
  const duration = current.live ? 'LIVE' : current.duration || formatDurationMs(current.durationMS);
  const volume = queue?.node?.volume ?? 80;
  const title = truncate(current.cleanTitle || current.title || 'Unknown Track', 180);
  const linkedTitle = current.url ? `[${title}](${current.url})` : `**${title}**`;

  const embed = new EmbedBuilder()
    .setColor(BRAND_COLOR)
    .setTitle(`${BRAND_NAME} - Now Playing`)
    .setDescription(`${linkedTitle}\n\nReadable, interactive, and clean controls for every listener.`)
    .addFields(
      { name: 'Progress', value: progressLine, inline: false },
      { name: 'Duration', value: `\`${duration}\``, inline: true },
      { name: 'Source', value: `\`${source}\``, inline: true },
      { name: 'Volume', value: `\`${volume}%\``, inline: true },
      { name: 'Requested By', value: requestedBy, inline: true },
      { name: 'Queue Length', value: `\`${queueSize} track(s)\``, inline: true },
      {
        name: 'Controls',
        value: 'Use buttons below for track changes, likes, and playlist shortcuts.',
        inline: false,
      },
    )
    .setFooter({ text: BRAND_NAME })
    .setTimestamp();

  if (current.thumbnail) {
    embed.setThumbnail(current.thumbnail);
  }

  return embed;
}

function buildQueueEmbed(queue) {
  const current = queue.currentTrack;
  const upcoming = queue.tracks.toArray().slice(0, MAX_QUEUE_PREVIEW);

  const embed = new EmbedBuilder()
    .setColor(SUCCESS_COLOR)
    .setTitle(`${BRAND_NAME} - Queue`)
    .setDescription(current ? `Now: **${truncate(current.cleanTitle || current.title || 'Unknown Track', 100)}**` : 'Queue is empty.')
    .setFooter({ text: `${queue.size} track(s) waiting` })
    .setTimestamp();

  if (upcoming.length > 0) {
    const lines = upcoming.map((item, index) => {
      const title = truncate(item.cleanTitle || item.title || 'Unknown Track', 60);
      const duration = item.live ? 'LIVE' : item.duration || formatDurationMs(item.durationMS);
      if (item.url) {
        return `${index + 1}. [${title}](${item.url}) - \`${duration}\``;
      }
      return `${index + 1}. ${title} - \`${duration}\``;
    });

    embed.addFields({
      name: 'Up Next',
      value: lines.join('\n'),
      inline: false,
    });
  }

  return embed;
}

function buildSearchEmbed(query, platform, results) {
  const config = getPlatformConfig(platform);

  const embed = new EmbedBuilder()
    .setColor(BRAND_COLOR)
    .setTitle(`${BRAND_NAME} - Search Results`)
    .setDescription(`Query: **${truncate(query, 140)}**\nPlatform: **${config.label}**`)
    .setTimestamp();

  if (!results.length) {
    embed.addFields({
      name: 'Results',
      value: 'No tracks found for this query.',
      inline: false,
    });
    return embed;
  }

  const lines = results.slice(0, 8).map((track, index) => {
    const title = truncate(track.cleanTitle || track.title || 'Unknown Track', 65);
    const author = truncate(track.author || 'Unknown Artist', 40);
    const duration = track.live ? 'LIVE' : track.duration || formatDurationMs(track.durationMS);
    if (track.url) {
      return `${index + 1}. [${title}](${track.url}) - ${author} - \`${duration}\``;
    }
    return `${index + 1}. ${title} - ${author} - \`${duration}\``;
  });

  embed.addFields({
    name: 'Top Matches',
    value: lines.join('\n'),
    inline: false,
  });

  return embed;
}

function buildLyricsEmbed(query, result) {
  const text = result?.plainLyrics || 'No lyrics found.';
  const preview = truncate(text, 3800);

  return new EmbedBuilder()
    .setColor(WARNING_COLOR)
    .setTitle(`${BRAND_NAME} - Lyrics`)
    .setDescription(`**${truncate(query, 160)}**\n\n${preview}`)
    .setFooter({ text: result ? `${result.trackName || ''} ${result.artistName ? `- ${result.artistName}` : ''}`.trim() : BRAND_NAME })
    .setTimestamp();
}

function buildHelpEmbed() {
  return new EmbedBuilder()
    .setColor(BRAND_COLOR)
    .setTitle(`${BRAND_NAME} - Command Guide`)
    .setDescription('Slash commands optimized for music playback and easy control.')
    .addFields(
      {
        name: 'Playback',
        value:
          '`/play`, `/search`, `/pause`, `/resume`, `/skip`, `/stop`, `/previous`, `/replay`, `/seek`, `/np`',
      },
      {
        name: 'Queue',
        value: '`/queue list`, `/shuffle`, `/remove`, `/loop`, `/volume`, `/autoplay`',
      },
      {
        name: 'Enhancements',
        value: '`/lyrics`, `/bassboost`, `/8d`, `/playlist show|play|remove|clear`, `/leave`',
      },
      {
        name: 'Platforms',
        value: 'Auto, YouTube, YouTube Music, Spotify, Apple Music, SoundCloud, Deezer, TIDAL',
      },
      {
        name: 'Autocomplete',
        value: 'Start typing in `/play query` or `/search query` to get song suggestions before submit.',
      },
    )
    .setFooter({ text: BRAND_NAME })
    .setTimestamp();
}

function buildFavoritesEmbed(user, favorites) {
  const top = favorites.slice(0, 10);
  const lines = top.map((track, index) => {
    const title = truncate(track.title || 'Unknown Track', 65);
    const duration = track.duration || 'Unknown';
    if (track.url) return `${index + 1}. [${title}](${track.url}) - \`${duration}\``;
    return `${index + 1}. ${title} - \`${duration}\``;
  });

  return new EmbedBuilder()
    .setColor(WARNING_COLOR)
    .setTitle(`${BRAND_NAME} - ${user.username}'s Playlist`)
    .setDescription(lines.length ? lines.join('\n') : 'No liked tracks yet. Use the Like button while music plays.')
    .setFooter({ text: `Total liked tracks: ${favorites.length}` })
    .setTimestamp();
}

async function safeReply(interaction, payload) {
  if (interaction.deferred || interaction.replied) {
    return interaction.followUp(payload);
  }
  return interaction.reply(payload);
}

async function getInteractionVoiceChannel(interaction) {
  const member = await interaction.guild.members.fetch(interaction.user.id);
  return member.voice.channel || null;
}

async function ensureVoiceAndPermissions(interaction) {
  if (!interaction.inGuild()) {
    await safeReply(interaction, { content: 'This command can only be used in a server.', flags: MessageFlags.Ephemeral });
    return { ok: false, channel: null };
  }

  const voiceChannel = await getInteractionVoiceChannel(interaction);
  if (!voiceChannel) {
    await safeReply(interaction, { content: 'Join a voice channel first, then try again.', flags: MessageFlags.Ephemeral });
    return { ok: false, channel: null };
  }

  const permissionCheck = getBotVoicePermissions(voiceChannel, interaction.guild);
  if (!permissionCheck.ok) {
    await safeReply(interaction, { content: permissionCheck.message, flags: MessageFlags.Ephemeral });
    return { ok: false, channel: null };
  }

  return { ok: true, channel: voiceChannel };
}

async function ensureSameVoiceChannel(interaction, queue) {
  const memberChannel = await getInteractionVoiceChannel(interaction);
  const queueChannel = queue?.channel;

  if (!memberChannel || !queueChannel || memberChannel.id !== queueChannel.id) {
    await safeReply(interaction, {
      content: 'Join my current voice channel to use this control.',
      flags: MessageFlags.Ephemeral,
    });
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

async function searchWithFallbackEngines(query, platform, requestedBy) {
  const resolved = resolveSearchOptions(query, platform);
  let lastError = null;

  for (const searchEngine of resolved.searchEngines) {
    try {
      const result = await player.search(resolved.query, {
        requestedBy,
        searchEngine,
        fallbackSearchEngine: resolved.fallbackSearchEngine,
      });

      if (result?.hasTracks?.()) {
        result.setTracks(prioritizeTracksForPlayback(result.tracks));
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

async function runSearch(query, platform, requestedBy) {
  const { result } = await searchWithFallbackEngines(query, platform, requestedBy);
  return result;
}

async function queueAndPlay(voiceChannel, query, textChannel, requestedBy, platform = 'auto') {
  const baseOptions = {
    requestedBy,
    nodeOptions: {
      metadata: {
        textChannel,
      },
      leaveOnEmpty: true,
      leaveOnEmptyCooldown: 60_000,
      leaveOnEnd: false,
      leaveOnStop: true,
      leaveOnStopCooldown: 10_000,
      skipOnNoStream: true,
      volume: 80,
    },
  };

  try {
    const { result: searchResult, usedEngine } = await searchWithFallbackEngines(query, platform, requestedBy);

    const result = await player.play(voiceChannel, searchResult, {
      ...baseOptions,
      searchEngine: usedEngine,
      fallbackSearchEngine: QueryType.YOUTUBE_SEARCH,
    });

    if (DEFAULT_AUTOPLAY && result.queue.repeatMode === QueueRepeatMode.OFF) {
      result.queue.setRepeatMode(QueueRepeatMode.AUTOPLAY);
    }

    return result;
  } catch (primaryError) {
    // Bridge fallback: retry through YouTube search when metadata-source playback cannot stream.
    try {
      const bridgeSearch = await searchWithFallbackEngines(query, 'auto', requestedBy);
      const fallbackTrack = bridgeSearch.result.tracks[0];
      const bridgeQuery = buildBridgeSearchQuery(fallbackTrack);

      if (bridgeQuery) {
        const bridged = await searchWithFallbackEngines(bridgeQuery, 'youtube', requestedBy);
        const bridgedResult = await player.play(voiceChannel, bridged.result, {
          ...baseOptions,
          searchEngine: bridged.usedEngine,
          fallbackSearchEngine: QueryType.YOUTUBE_SEARCH,
        });

        if (DEFAULT_AUTOPLAY && bridgedResult.queue.repeatMode === QueueRepeatMode.OFF) {
          bridgedResult.queue.setRepeatMode(QueueRepeatMode.AUTOPLAY);
        }

        return bridgedResult;
      }
    } catch {
      // ignore and throw original error below
    }
    throw primaryError;
  }
}

async function refreshNowPlayingMessage(queue) {
  try {
    const entry = nowPlayingRegistry.get(queue.guild.id);
    if (!entry) return;

    const channel = await client.channels.fetch(entry.channelId).catch(() => null);
    if (!channel || !channel.isTextBased()) {
      nowPlayingRegistry.delete(queue.guild.id);
      return;
    }

    const message = await channel.messages.fetch(entry.messageId).catch(() => null);
    if (!message) {
      nowPlayingRegistry.delete(queue.guild.id);
      return;
    }

    await message.edit({
      embeds: [buildNowPlayingEmbed(queue)],
      components: [buildControlsRow()],
    });
  } catch {
    // no-op
  }
}

function setNowPlayingRegistry(queue, message) {
  nowPlayingRegistry.set(queue.guild.id, {
    channelId: message.channel.id,
    messageId: message.id,
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

  try {
    const searchResult = await runSearch(query, platform, interaction.user);
    const tracks = searchResult.tracks.slice(0, MAX_AUTOCOMPLETE_CHOICES);

    const choices = tracks.map((track) => {
      const label = truncate(`${track.cleanTitle || track.title} - ${track.author || 'Unknown'}`, 100);
      const value = truncate(track.cleanTitle || track.title || query, 100);
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
    await safeReply(interaction, {
      content: 'Please wait a moment before using /play again.',
      flags: MessageFlags.Ephemeral,
    });
    return;
  }

  const voiceCheck = await ensureVoiceAndPermissions(interaction);
  if (!voiceCheck.ok) return;

  const query = interaction.options.getString('query', true);
  const platform = interaction.options.getString('platform') || 'auto';

  await interaction.deferReply();

  try {
    const { track } = await queueAndPlay(voiceCheck.channel, query, interaction.channel, interaction.user, platform);
    await interaction.editReply(`Queued **${track.cleanTitle || track.title}**.`);
  } catch (error) {
    console.error('[Play Error]', error);
    await interaction.editReply(`I could not play that track: ${error.message || error}`);
  }
}

async function handleSearch(interaction) {
  const query = interaction.options.getString('query', true);
  const platform = interaction.options.getString('platform') || 'auto';

  await interaction.deferReply({ flags: MessageFlags.Ephemeral });

  try {
    const searchResult = await runSearch(query, platform, interaction.user);
    await interaction.editReply({
      embeds: [buildSearchEmbed(query, platform, searchResult.tracks)],
    });
  } catch (error) {
    console.error('[Search Error]', error);
    await interaction.editReply({ content: `Search failed: ${error.message || error}` });
  }
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
    await safeReply(interaction, {
      content: removed > 0 ? `Cleared ${removed} track(s) from your liked playlist.` : 'Your liked playlist is already empty.',
      flags: MessageFlags.Ephemeral,
    });
    return;
  }

  if (subcommand === 'remove') {
    const position = interaction.options.getInteger('track', true);
    const { removed, total } = removeFavoriteByIndex(interaction.user.id, position);

    if (!removed) {
      await safeReply(interaction, { content: 'That track number does not exist.', flags: MessageFlags.Ephemeral });
      return;
    }

    await safeReply(interaction, {
      content: `Removed **${removed.title}**. ${total} track(s) remaining.`,
      flags: MessageFlags.Ephemeral,
    });
    return;
  }

  if (subcommand === 'play') {
    if (!favorites.length) {
      await safeReply(interaction, {
        content: 'Your liked playlist is empty. Use the Like button first.',
        flags: MessageFlags.Ephemeral,
      });
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

      await interaction.editReply(`Loaded playlist: now playing 1 track and queued ${added} additional track(s).`);
    } catch (error) {
      console.error('[Playlist Play Error]', error);
      await interaction.editReply(`I could not load your playlist: ${error.message || error}`);
    }
  }
}

async function handleLyrics(interaction, queue) {
  const customQuery = interaction.options.getString('query');
  const query = customQuery || (queue?.currentTrack ? `${queue.currentTrack.title} ${queue.currentTrack.author || ''}`.trim() : null);

  if (!query) {
    await safeReply(interaction, {
      content: 'Provide a song name or play a track first.',
      flags: MessageFlags.Ephemeral,
    });
    return;
  }

  await interaction.deferReply({ flags: MessageFlags.Ephemeral });

  try {
    const results = await player.lyrics.search({ q: query });
    const first = results?.[0];

    if (!first || !first.plainLyrics) {
      await interaction.editReply({ content: 'No lyrics found for that query.' });
      return;
    }

    await interaction.editReply({
      embeds: [buildLyricsEmbed(query, first)],
    });
  } catch (error) {
    console.error('[Lyrics Error]', error);
    await interaction.editReply({ content: `Lyrics lookup failed: ${error.message || error}` });
  }
}

async function handleLoop(interaction, queue) {
  const mode = interaction.options.getString('mode', true);

  if (mode === 'all') {
    queue.setRepeatMode(QueueRepeatMode.QUEUE);
    await safeReply(interaction, { content: 'Loop mode set to **all**.' });
    return;
  }

  if (mode === 'current') {
    queue.setRepeatMode(QueueRepeatMode.TRACK);
    await safeReply(interaction, { content: 'Loop mode set to **current track**.' });
    return;
  }

  queue.setRepeatMode(QueueRepeatMode.OFF);
  await safeReply(interaction, { content: 'Loop mode disabled.' });
}

async function handleAutoplay(interaction, queue) {
  const mode = interaction.options.getString('mode', true);

  if (mode === 'on') {
    queue.setRepeatMode(QueueRepeatMode.AUTOPLAY);
    await safeReply(interaction, { content: 'Autoplay enabled.' });
    return;
  }

  queue.setRepeatMode(QueueRepeatMode.OFF);
  await safeReply(interaction, { content: 'Autoplay disabled.' });
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
  const label = mode === 'off' ? 'disabled' : `set to ${mode}`;
  await safeReply(interaction, { content: `Bassboost ${label}.` });
}

async function handle8D(interaction, queue) {
  const mode = interaction.options.getString('mode', true);

  if (mode === 'on') {
    await queue.filters.ffmpeg.setFilters({ '8D': true });
    await safeReply(interaction, { content: '8D filter enabled.' });
    return;
  }

  await queue.filters.ffmpeg.setFilters({ '8D': false });
  await safeReply(interaction, { content: '8D filter disabled.' });
}

async function handleQueueSubcommands(interaction, queue) {
  const subcommand = interaction.options.getSubcommand();

  if (subcommand === 'list') {
    if (!hasActiveTrack(queue)) {
      await safeReply(interaction, { content: 'Queue is currently empty.', flags: MessageFlags.Ephemeral });
      return;
    }

    await safeReply(interaction, { embeds: [buildQueueEmbed(queue)] });
    return;
  }

  if (subcommand === 'clear') {
    if (!queue || queue.size === 0) {
      await safeReply(interaction, { content: 'Queue is already empty.', flags: MessageFlags.Ephemeral });
      return;
    }

    queue.clear();
    await safeReply(interaction, { content: 'Queue cleared.' });
  }
}

async function handleCommandInteraction(interaction) {
  if (!interaction.isChatInputCommand()) return;

  try {
    if (interaction.commandName === 'play') {
      await handlePlay(interaction);
      return;
    }

    if (interaction.commandName === 'search') {
      await handleSearch(interaction);
      return;
    }

    if (interaction.commandName === 'help') {
      await safeReply(interaction, { embeds: [buildHelpEmbed()], flags: MessageFlags.Ephemeral });
      return;
    }

    if (!interaction.inGuild()) {
      await safeReply(interaction, { content: 'This command can only be used in a server.', flags: MessageFlags.Ephemeral });
      return;
    }

    const queue = getQueue(interaction.guildId);

    if (interaction.commandName === 'playlist') {
      await handlePlaylist(interaction);
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
        await safeReply(interaction, { content: 'Nothing is currently playing.', flags: MessageFlags.Ephemeral });
        return;
      }

      await safeReply(interaction, {
        embeds: [buildNowPlayingEmbed(queue)],
        components: [buildControlsRow()],
      });
      return;
    }

    if (interaction.commandName === 'leave') {
      if (!queue) {
        await safeReply(interaction, { content: 'I am not connected to a voice channel.', flags: MessageFlags.Ephemeral });
        return;
      }

      queue.delete();
      nowPlayingRegistry.delete(interaction.guildId);
      await safeReply(interaction, { content: 'Disconnected from voice channel.' });
      return;
    }

    if (interaction.commandName === 'stop') {
      if (!hasActiveTrack(queue)) {
        await safeReply(interaction, { content: 'Nothing is currently playing.', flags: MessageFlags.Ephemeral });
        return;
      }

      if (!(await ensureSameVoiceChannel(interaction, queue))) return;
      queue.node.stop();
      await safeReply(interaction, { content: 'Playback stopped.' });
      return;
    }

    if (!queue) {
      await safeReply(interaction, { content: 'No active queue. Start with `/play` first.', flags: MessageFlags.Ephemeral });
      return;
    }

    if (!(await ensureSameVoiceChannel(interaction, queue))) return;

    if (interaction.commandName === 'pause') {
      if (!hasActiveTrack(queue)) {
        await safeReply(interaction, { content: 'Nothing is currently playing.', flags: MessageFlags.Ephemeral });
        return;
      }

      if (queue.node.isPaused()) {
        await safeReply(interaction, { content: 'Playback is already paused.', flags: MessageFlags.Ephemeral });
        return;
      }

      queue.node.pause();
      await safeReply(interaction, { content: 'Playback paused.' });
      await refreshNowPlayingMessage(queue);
      return;
    }

    if (interaction.commandName === 'resume') {
      if (!hasActiveTrack(queue)) {
        await safeReply(interaction, { content: 'Nothing is currently playing.', flags: MessageFlags.Ephemeral });
        return;
      }

      if (!queue.node.isPaused()) {
        await safeReply(interaction, { content: 'Playback is already running.', flags: MessageFlags.Ephemeral });
        return;
      }

      queue.node.resume();
      await safeReply(interaction, { content: 'Playback resumed.' });
      await refreshNowPlayingMessage(queue);
      return;
    }

    if (interaction.commandName === 'skip') {
      if (!hasActiveTrack(queue)) {
        await safeReply(interaction, { content: 'Nothing is currently playing.', flags: MessageFlags.Ephemeral });
        return;
      }

      const amount = interaction.options.getInteger('count') || 1;
      let skipped = 0;

      for (let i = 0; i < amount; i += 1) {
        if (queue.node.skip()) skipped += 1;
        else break;
      }

      await safeReply(interaction, {
        content: skipped > 0 ? `Skipped ${skipped} track(s).` : 'I could not skip track(s).',
      });
      return;
    }

    if (interaction.commandName === 'shuffle') {
      if (queue.size < 2) {
        await safeReply(interaction, { content: 'Need at least 2 tracks in queue to shuffle.', flags: MessageFlags.Ephemeral });
        return;
      }

      queue.tracks.shuffle();
      await safeReply(interaction, { content: 'Queue shuffled.' });
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
      const changed = queue.node.setVolume(value);
      await safeReply(interaction, {
        content: changed ? `Volume set to ${value}%.` : 'Could not change volume.',
      });
      return;
    }

    if (interaction.commandName === 'remove') {
      const position = interaction.options.getInteger('position', true);
      const track = queue.tracks.at(position - 1);

      if (!track) {
        await safeReply(interaction, {
          content: 'That queue position does not exist.',
          flags: MessageFlags.Ephemeral,
        });
        return;
      }

      queue.node.remove(track);
      await safeReply(interaction, {
        content: `Removed **${track.cleanTitle || track.title}** from queue.`,
      });
      return;
    }

    if (interaction.commandName === 'replay') {
      if (!hasActiveTrack(queue)) {
        await safeReply(interaction, { content: 'Nothing is currently playing.', flags: MessageFlags.Ephemeral });
        return;
      }

      await queue.node.seek(0);
      await safeReply(interaction, { content: 'Replaying current track from the start.' });
      return;
    }

    if (interaction.commandName === 'seek') {
      if (!hasActiveTrack(queue)) {
        await safeReply(interaction, { content: 'Nothing is currently playing.', flags: MessageFlags.Ephemeral });
        return;
      }

      const input = interaction.options.getString('position', true);
      const targetMs = parseTimeToMs(input);

      if (targetMs == null) {
        await safeReply(interaction, {
          content: 'Invalid seek time. Use `90`, `1:30`, or `00:01:30`.',
          flags: MessageFlags.Ephemeral,
        });
        return;
      }

      const current = queue.currentTrack;
      const durationMs = current?.durationMS || 0;

      if (!current?.live && durationMs > 0 && targetMs > durationMs) {
        await safeReply(interaction, {
          content: `Seek time is beyond track length (${formatDurationMs(durationMs)}).`,
          flags: MessageFlags.Ephemeral,
        });
        return;
      }

      const ok = await queue.node.seek(targetMs);
      await safeReply(interaction, {
        content: ok ? `Seeked to ${formatDurationMs(targetMs)}.` : 'Could not seek this track.',
      });
      return;
    }

    if (interaction.commandName === 'previous') {
      if (!queue.history.previousTrack) {
        await safeReply(interaction, {
          content: 'No previous track in listening history.',
          flags: MessageFlags.Ephemeral,
        });
        return;
      }

      await queue.history.previous();
      await safeReply(interaction, { content: 'Went back to previous track.' });
      return;
    }

    if (interaction.commandName === 'bassboost') {
      await handleBassBoost(interaction, queue);
      return;
    }

    if (interaction.commandName === '8d') {
      await handle8D(interaction, queue);
    }
  } catch (error) {
    console.error('[Interaction Error]', error);
    if (interaction.deferred || interaction.replied) {
      await interaction.followUp({ content: `Error: ${error.message || error}`, flags: MessageFlags.Ephemeral }).catch(() => null);
    } else {
      await interaction.reply({ content: `Error: ${error.message || error}`, flags: MessageFlags.Ephemeral }).catch(() => null);
    }
  }
}

async function handleButtonInteraction(interaction) {
  if (!interaction.isButton()) return;
  if (!Object.values(BUTTON_IDS).includes(interaction.customId)) return;

  if (!interaction.inGuild()) {
    await interaction.reply({ content: 'These controls only work in servers.', flags: MessageFlags.Ephemeral });
    return;
  }

  const queue = getQueue(interaction.guildId);
  if (!queue || !hasActiveTrack(queue)) {
    await interaction.reply({ content: 'Nothing is currently playing.', flags: MessageFlags.Ephemeral });
    return;
  }

  const allowed = await ensureSameVoiceChannel(interaction, queue);
  if (!allowed) return;

  try {
    if (interaction.customId === BUTTON_IDS.PAUSE_RESUME) {
      if (queue.node.isPaused()) {
        queue.node.resume();
        await interaction.reply({ content: 'Playback resumed.', flags: MessageFlags.Ephemeral });
      } else {
        queue.node.pause();
        await interaction.reply({ content: 'Playback paused.', flags: MessageFlags.Ephemeral });
      }

      await refreshNowPlayingMessage(queue);
      return;
    }

    if (interaction.customId === BUTTON_IDS.SKIP) {
      const skipped = queue.node.skip();
      await interaction.reply({
        content: skipped ? 'Skipped current track.' : 'Could not skip current track.',
        flags: MessageFlags.Ephemeral,
      });
      return;
    }

    if (interaction.customId === BUTTON_IDS.STOP) {
      queue.node.stop();
      await interaction.reply({ content: 'Playback stopped.', flags: MessageFlags.Ephemeral });
      return;
    }

    if (interaction.customId === BUTTON_IDS.LIKE) {
      const currentTrack = queue.currentTrack;
      if (!currentTrack) {
        await interaction.reply({ content: 'No active track to like.', flags: MessageFlags.Ephemeral });
        return;
      }

      const result = saveTrackToFavorites(interaction.user.id, currentTrack);
      if (result.added) {
        await interaction.reply({
          content: `Saved **${result.track.title}** to your playlist. Total: ${result.total}.`,
          flags: MessageFlags.Ephemeral,
        });
      } else {
        await interaction.reply({
          content: `**${result.track.title}** is already in your playlist.`,
          flags: MessageFlags.Ephemeral,
        });
      }
      return;
    }

    if (interaction.customId === BUTTON_IDS.PLAYLIST) {
      const favorites = getUserFavorites(interaction.user.id);
      await interaction.reply({
        embeds: [buildFavoritesEmbed(interaction.user, favorites)],
        flags: MessageFlags.Ephemeral,
      });
    }
  } catch (error) {
    console.error('[Button Error]', error);
    if (!interaction.replied && !interaction.deferred) {
      await interaction.reply({ content: `Error: ${error.message || error}`, flags: MessageFlags.Ephemeral }).catch(() => null);
    }
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
      ),

    new SlashCommandBuilder()
      .setName('queue')
      .setDescription('Queue actions')
      .addSubcommand((sub) => sub.setName('list').setDescription('Shows the current queue for this server'))
      .addSubcommand((sub) => sub.setName('clear').setDescription('Clears all upcoming tracks in queue')),

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
  ].map((command) => command.toJSON());

  const rest = new REST({ version: '10' }).setToken(TOKEN);

  if (GUILD_ID) {
    await rest.put(Routes.applicationGuildCommands(CLIENT_ID, GUILD_ID), { body: commands });
    console.log(`[Slash Commands] Registered to guild ${GUILD_ID}.`);
    return;
  }

  await rest.put(Routes.applicationCommands(CLIENT_ID), { body: commands });
  console.log('[Slash Commands] Registered globally (can take up to 1 hour to appear).');
}

player.events.on('playerStart', async (queue, track) => {
  const channel = queue.metadata?.textChannel;
  if (!channel || typeof channel.send !== 'function') return;
  lastTrackStartTimes.set(queue.guild.id, Date.now());

  try {
    const existing = nowPlayingRegistry.get(queue.guild.id);
    if (existing) {
      const storedChannel = await client.channels.fetch(existing.channelId).catch(() => null);
      if (storedChannel && storedChannel.isTextBased()) {
        const storedMessage = await storedChannel.messages.fetch(existing.messageId).catch(() => null);
        if (storedMessage) {
          await storedMessage.edit({
            embeds: [buildNowPlayingEmbed(queue, track)],
            components: [buildControlsRow()],
          });
          return;
        }
      }
    }

    const message = await channel.send({
      embeds: [buildNowPlayingEmbed(queue, track)],
      components: [buildControlsRow()],
    });
    setNowPlayingRegistry(queue, message);
  } catch {
    // ignore send errors
  }
});

player.events.on('playerPause', async (queue) => {
  await refreshNowPlayingMessage(queue);
});

player.events.on('playerResume', async (queue) => {
  await refreshNowPlayingMessage(queue);
});

player.events.on('playerSkip', async (queue) => {
  await refreshNowPlayingMessage(queue);
});

player.events.on('emptyQueue', (queue) => {
  const channel = queue.metadata?.textChannel;
  if (!channel || typeof channel.send !== 'function') return;

  const startedAt = lastTrackStartTimes.get(queue.guild.id) || 0;
  if (startedAt > 0 && Date.now() - startedAt < 4_000) {
    // Avoid noisy "queue ended" spam for instant stream failures.
    return;
  }

  if (!canSendGuildMessage(queue.guild.id, 'emptyQueue', 120_000)) return;
  channel.send('Queue ended. Add another song when you are ready.').catch(() => null);
});

player.events.on('error', (queue, error) => {
  console.error('[Queue Error]', error);

  const channel = queue?.metadata?.textChannel;
  if (!channel || typeof channel.send !== 'function') return;

  if (!canSendGuildMessage(queue.guild.id, 'queueError', 60_000)) return;
  channel.send('Playback error occurred. Please try `/play` again.').catch(() => null);
});

player.events.on('playerError', (queue, error, track) => {
  console.error('[Player Error]', error, track?.title || track?.cleanTitle || 'unknown track');

  const channel = queue?.metadata?.textChannel;
  if (!channel || typeof channel.send !== 'function') return;

  if (!canSendGuildMessage(queue.guild.id, 'playerError', 60_000)) return;
  channel.send('I joined the channel but could not stream this track. Try another query or source.').catch(() => null);
});

client.on(Events.InteractionCreate, async (interaction) => {
  const handledAutocomplete = await handleAutocomplete(interaction);
  if (handledAutocomplete) return;

  await handleCommandInteraction(interaction);
  await handleButtonInteraction(interaction);
});

client.once(Events.ClientReady, async (readyClient) => {
  console.log(`Logged in as ${readyClient.user.tag}`);
  console.log(`[Startup] FFmpeg path: ${resolvedFFmpegPath || 'auto-detect'}`);
  try {
    const extractorIds = Array.from(player.extractors.store.keys?.() || []);
    console.log(`[Startup] Extractors loaded: ${extractorIds.join(', ') || 'none'}`);
  } catch {
    // no-op
  }

  try {
    const depsReport = player.scanDeps();
    console.log(depsReport);

    if (/"hasLibopus"\s*:\s*false/i.test(depsReport) || /\blibopus\s*:\s*false/i.test(depsReport)) {
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
      }),
    );
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
      await player.extractors.register(YoutubeiExtractor, {});
      console.log('[Startup] YouTube extractor registered (discord-player-youtubei).');
    } catch (error) {
      console.warn('[Startup] YouTube extractor failed to initialize:', error?.message || error);
    }
  } else {
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









