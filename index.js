'use strict';

require('dotenv').config();

const http = require('node:http');
const {
  Client,
  GatewayIntentBits,
  Events,
  REST,
  Routes,
  SlashCommandBuilder,
  PermissionFlagsBits,
} = require('discord.js');
const { Player } = require('discord-player');
const { DefaultExtractors } = require('@discord-player/extractor');
const ffmpegPath = require('ffmpeg-static');

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

const CLIENT_ID =
  process.env.DISCORD_CLIENT_ID || process.env.CLIENT_ID || inferClientIdFromToken(TOKEN) || null;
const GUILD_ID = process.env.DISCORD_GUILD_ID || process.env.GUILD_ID || null;
const PREFIX = process.env.PREFIX || '!';

if (!TOKEN) {
  throw new Error('Missing DISCORD_TOKEN in .env');
}

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildVoiceStates,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ],
});

const player = new Player(client, {
  ffmpegPath: ffmpegPath || undefined,
});

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
    return { ok: false, message: 'I need the **Connect** permission in your voice channel.' };
  }

  if (!perms.has(PermissionFlagsBits.Speak)) {
    return { ok: false, message: 'I need the **Speak** permission in your voice channel.' };
  }

  return { ok: true, message: '' };
}

function getQueue(guildId) {
  return player.nodes.get(guildId);
}

async function queueAndPlay(voiceChannel, query, textChannel, requestedBy) {
  return player.play(voiceChannel, query, {
    requestedBy,
    nodeOptions: {
      metadata: {
        textChannel,
      },
      leaveOnEmpty: true,
      leaveOnEmptyCooldown: 60_000,
      leaveOnEnd: true,
      leaveOnEndCooldown: 300_000,
      volume: 80,
    },
  });
}

async function handlePlayInteraction(interaction) {
  if (!interaction.inGuild()) {
    await interaction.reply({ content: 'This command can only be used in a server.', ephemeral: true });
    return;
  }

  const member = await interaction.guild.members.fetch(interaction.user.id);
  const voiceChannel = member.voice.channel;
  if (!voiceChannel) {
    await interaction.reply({ content: 'Join a voice channel first, then run `/play`.', ephemeral: true });
    return;
  }

  const permissionCheck = getBotVoicePermissions(voiceChannel, interaction.guild);
  if (!permissionCheck.ok) {
    await interaction.reply({ content: permissionCheck.message, ephemeral: true });
    return;
  }

  const query = interaction.options.getString('query', true);
  await interaction.deferReply();

  try {
    const { track } = await queueAndPlay(voiceChannel, query, interaction.channel, interaction.user);
    await interaction.followUp(`Queued **${track.cleanTitle}**.`);
  } catch (error) {
    console.error('[Play Interaction Error]', error);
    await interaction.followUp(`I could not play that track: ${error.message || error}`);
  }
}

async function handlePlayMessage(message, query) {
  const voiceChannel = message.member?.voice?.channel;
  if (!voiceChannel) {
    await message.reply('Join a voice channel first, then use this command again.');
    return;
  }

  const permissionCheck = getBotVoicePermissions(voiceChannel, message.guild);
  if (!permissionCheck.ok) {
    await message.reply(permissionCheck.message);
    return;
  }

  try {
    const { track } = await queueAndPlay(voiceChannel, query, message.channel, message.author);
    await message.reply(`Queued **${track.cleanTitle}**.`);
  } catch (error) {
    console.error('[Play Message Error]', error);
    await message.reply(`I could not play that track: ${error.message || error}`);
  }
}

async function registerSlashCommands() {
  if (!CLIENT_ID) {
    console.warn('[Slash Commands] DISCORD_CLIENT_ID is missing; skipping slash command registration.');
    return;
  }

  const commands = [
    new SlashCommandBuilder()
      .setName('play')
      .setDescription('Play music from a URL or search text')
      .addStringOption((option) =>
        option
          .setName('query')
          .setDescription('Song name or URL')
          .setRequired(true),
      ),
    new SlashCommandBuilder().setName('skip').setDescription('Skip the current track'),
    new SlashCommandBuilder().setName('stop').setDescription('Stop playback'),
    new SlashCommandBuilder().setName('leave').setDescription('Leave the voice channel'),
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

player.events.on('playerStart', (queue, track) => {
  const channel = queue.metadata?.textChannel;
  if (channel && typeof channel.send === 'function') {
    channel.send(`Now playing **${track.cleanTitle}**.`).catch(() => null);
  }
});

player.events.on('error', (queue, error) => {
  console.error('[Queue Error]', error);
  const channel = queue?.metadata?.textChannel;
  if (channel && typeof channel.send === 'function') {
    channel.send(`Queue error: ${error.message || error}`).catch(() => null);
  }
});

player.events.on('playerError', (queue, error, track) => {
  console.error('[Player Error]', error);
  const channel = queue?.metadata?.textChannel;
  if (channel && typeof channel.send === 'function') {
    channel.send(`Track error on **${track?.cleanTitle || 'unknown'}**: ${error.message || error}`).catch(() => null);
  }
});

client.on(Events.InteractionCreate, async (interaction) => {
  if (!interaction.isChatInputCommand()) return;

  try {
    if (interaction.commandName === 'play') {
      await handlePlayInteraction(interaction);
      return;
    }

    if (!interaction.inGuild()) {
      await interaction.reply({ content: 'This command can only be used in a server.', ephemeral: true });
      return;
    }

    const queue = getQueue(interaction.guildId);

    if (interaction.commandName === 'skip') {
      if (!queue || !queue.isPlaying()) {
        await interaction.reply({ content: 'Nothing is currently playing.', ephemeral: true });
        return;
      }

      const skipped = queue.node.skip();
      await interaction.reply(skipped ? 'Skipped the current track.' : 'I could not skip the track.');
      return;
    }

    if (interaction.commandName === 'stop') {
      if (!queue || !queue.isPlaying()) {
        await interaction.reply({ content: 'Nothing is currently playing.', ephemeral: true });
        return;
      }

      queue.node.stop();
      await interaction.reply('Stopped playback.');
      return;
    }

    if (interaction.commandName === 'leave') {
      if (!queue) {
        await interaction.reply({ content: 'I am not connected to a voice channel.', ephemeral: true });
        return;
      }

      queue.delete();
      await interaction.reply('Left the voice channel.');
    }
  } catch (error) {
    console.error('[Interaction Handler Error]', error);
    if (interaction.deferred || interaction.replied) {
      await interaction.followUp({ content: `Error: ${error.message || error}`, ephemeral: true }).catch(() => null);
    } else {
      await interaction.reply({ content: `Error: ${error.message || error}`, ephemeral: true }).catch(() => null);
    }
  }
});

client.on(Events.MessageCreate, async (message) => {
  if (!message.guild || message.author.bot) return;
  if (!message.content.startsWith(PREFIX)) return;

  const args = message.content.slice(PREFIX.length).trim().split(/\s+/);
  const commandName = (args.shift() || '').toLowerCase();

  try {
    if (commandName === 'play') {
      const query = args.join(' ').trim();
      if (!query) {
        await message.reply(`Usage: ${PREFIX}play <song name or url>`);
        return;
      }

      await handlePlayMessage(message, query);
      return;
    }

    const queue = getQueue(message.guild.id);

    if (commandName === 'skip') {
      if (!queue || !queue.isPlaying()) {
        await message.reply('Nothing is currently playing.');
        return;
      }

      const skipped = queue.node.skip();
      await message.reply(skipped ? 'Skipped the current track.' : 'I could not skip the track.');
      return;
    }

    if (commandName === 'stop') {
      if (!queue || !queue.isPlaying()) {
        await message.reply('Nothing is currently playing.');
        return;
      }

      queue.node.stop();
      await message.reply('Stopped playback.');
      return;
    }

    if (commandName === 'leave') {
      if (!queue) {
        await message.reply('I am not connected to a voice channel.');
        return;
      }

      queue.delete();
      await message.reply('Left the voice channel.');
      return;
    }

    if (commandName === 'help') {
      await message.reply(
        `Commands: ${PREFIX}play <query>, ${PREFIX}skip, ${PREFIX}stop, ${PREFIX}leave\n` +
          'Slash commands: /play, /skip, /stop, /leave',
      );
    }
  } catch (error) {
    console.error('[Message Handler Error]', error);
    await message.reply(`Error: ${error.message || error}`).catch(() => null);
  }
});

client.once(Events.ClientReady, async (readyClient) => {
  console.log(`Logged in as ${readyClient.user.tag}`);

  try {
    await registerSlashCommands();
  } catch (error) {
    console.error('[Slash Command Registration Error]', error);
  }
});

async function bootstrap() {
  await player.extractors.loadMulti(DefaultExtractors);
  await client.login(TOKEN);
}

if (process.env.PORT) {
  const port = Number(process.env.PORT);
  const server = http.createServer((_, res) => {
    res.statusCode = 200;
    res.setHeader('Content-Type', 'text/plain');
    res.end('SyncInk Radio bot is running.\n');
  });

  server.listen(port, () => {
    console.log(`[Health] HTTP server listening on ${port}`);
  });
}

bootstrap().catch((error) => {
  console.error('[Startup Error]', error);
  process.exit(1);
});


