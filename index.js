require('dotenv').config();
const fs = require('fs');
const { Client, GatewayIntentBits, REST, Routes, EmbedBuilder } = require('discord.js');
const {
    joinVoiceChannel,
    createAudioPlayer,
    createAudioResource,
    AudioPlayerStatus,
    VoiceConnectionStatus,
    entersState,
    StreamType
} = require('@discordjs/voice');
const { spawn } = require('child_process');

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildVoiceStates,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent
    ]
});

const queues    = new Map();
const COOK_PATH = '/tmp/yt-cookies.txt';

if (process.env.YOUTUBE_COOKIES) {
    fs.writeFileSync(COOK_PATH, process.env.YOUTUBE_COOKIES);
    console.log('✅ YouTube cookies loaded from env');
} else {
    console.warn('⚠️  YOUTUBE_COOKIES env variable is NOT set');
}

function cookieArgs() {
    return fs.existsSync(COOK_PATH) ? ['--cookies', COOK_PATH] : [];
}

function formatDuration(seconds) {
    if (!seconds) return 'Live';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    return `${m}:${String(s).padStart(2,'0')}`;
}

function searchTrack(query) {
    return new Promise((resolve, reject) => {
        const isUrl  = /^https?:\/\//.test(query);
        const target = isUrl ? query : `ytsearch1:${query}`;

        const proc = spawn('yt-dlp', [
            '--no-playlist',
            '-j',
            '--no-warnings',
            '--no-check-formats',
            ...cookieArgs(),
            target
        ]);

        let out = '', err = '';
        proc.stdout.on('data', d => out += d);
        proc.stderr.on('data', d => err += d);

        proc.on('close', code => {
            if (code !== 0) return reject(new Error(`Search failed: ${err.trim()}`));
            try {
                const info = JSON.parse(out.trim().split('\n')[0]);
                resolve({
                    title:     info.title    || 'Unknown Title',
                    url:       info.webpage_url || info.original_url || info.url,
                    thumbnail: info.thumbnail || null,
                    author:    info.uploader  || info.channel || 'Unknown',
                    duration:  formatDuration(info.duration)
                });
            } catch (e) { reject(new Error('Could not parse track info')); }
        });

        proc.on('error', e => reject(new Error(`yt-dlp not found: ${e.message}`)));
    });
}

function createAudioStream(pageUrl, volume = 0.8) {
    const ytdlp = spawn('yt-dlp', [
        '--no-playlist',
        '-f', 'bestaudio[ext=webm]/bestaudio[ext=m4a]/bestaudio/best',
        '--no-check-formats',
        ...cookieArgs(),
        '-o', '-',
        '--quiet',
        '--no-warnings',
        pageUrl
    ]);

    const ffmpeg = spawn('ffmpeg', [
        '-i',        'pipe:0',
        '-vn',
        '-f',        's16le',
        '-ar',       '48000',
        '-ac',       '2',
        '-af',       `volume=${volume}`,
        '-loglevel', 'error',
        'pipe:1'
    ], { stdio: ['pipe', 'pipe', 'pipe'] });

    ytdlp.stdout.pipe(ffmpeg.stdin);

    ytdlp.stderr.on('data',  d => { const m = d.toString().trim(); if (m) console.log('[yt-dlp]', m); });
    ffmpeg.stderr.on('data', d => { const m = d.toString().trim(); if (m) console.log('[ffmpeg]', m); });
    ytdlp.on('error',  e => console.error('[yt-dlp error]',  e.message));
    ffmpeg.on('error', e => console.error('[ffmpeg error]',  e.message));
    ytdlp.on('close',  code => { if (code !== 0) console.log(`[yt-dlp] exit ${code}`); ffmpeg.stdin.end(); });

    return ffmpeg.stdout;
}

async function playNext(guildId) {
    const entry = queues.get(guildId);
    if (!entry || entry.tracks.length === 0) { if (entry) entry.playing = false; return; }

    entry.playing = true;
    const track   = entry.tracks[0];

    try {
        console.log(`[play] ${track.title}`);
        await entersState(entry.connection, VoiceConnectionStatus.Ready, 20_000);
        console.log('[play] Voice connection ready ✅');

        const stream   = createAudioStream(track.url, entry.volume);
        const resource = createAudioResource(stream, { inputType: StreamType.Raw });
        entry.currentResource = resource;
        entry.player.play(resource);
        console.log('[play] player.play() called ✅');

    } catch (e) {
        console.error('[playNext error]', e.message);
        entry.tracks.shift();
        playNext(guildId);
    }
}

async function getOrCreateEntry(guildId, voiceChannel, guild) {
    const existing = queues.get(guildId);
    if (existing && existing.connection.state.status !== VoiceConnectionStatus.Destroyed) return existing;

    const connection = joinVoiceChannel({
        channelId:      voiceChannel.id,
        guildId,
        adapterCreator: guild.voiceAdapterCreator,
        selfDeaf:       true
    });

    const player = createAudioPlayer();

    player.on('stateChange', (o, n) => console.log(`[player] ${o.status} → ${n.status}`));

    player.on(AudioPlayerStatus.Idle, () => {
        const entry = queues.get(guildId);
        if (!entry) return;
        entry.tracks.shift();
        entry.tracks.length > 0 ? playNext(guildId) : (entry.playing = false);
    });

    player.on('error', err => {
        console.error('[player error]', err.message);
        const entry = queues.get(guildId);
        if (!entry) return;
        entry.tracks.shift();
        entry.tracks.length > 0 ? playNext(guildId) : (entry.playing = false);
    });

    connection.on('stateChange', (o, n) => console.log(`[connection] ${o.status} → ${n.status}`));
    connection.subscribe(player);

    const entry = { connection, player, tracks: [], volume: 0.8, playing: false, currentResource: null };
    queues.set(guildId, entry);
    return entry;
}

const commands = [
    { name: 'play', description: 'Play a song', options: [{ name: 'query', type: 3, description: 'Song name or URL', required: true }] },
    { name: 'skip',       description: 'Skip current song' },
    { name: 'pause',      description: 'Pause playback' },
    { name: 'resume',     description: 'Resume playback' },
    { name: 'stop',       description: 'Stop and disconnect' },
    { name: 'volume',     description: 'Set volume 1-100', options: [{ name: 'amount', type: 4, description: 'Volume 1-100', required: true }] },
    { name: 'queue',      description: 'Show queue' },
    { name: 'nowplaying', description: 'Show current song' }
];

client.once('ready', async () => {
    console.log(`✅ Online as ${client.user.tag}`);
    const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
    await rest.put(Routes.applicationCommands(client.user.id), { body: commands });
    console.log('✅ Commands registered!');
});

client.on('interactionCreate', async interaction => {
    if (!interaction.isChatInputCommand()) return;
    const { commandName, guildId, member, guild } = interaction;
    const voiceChannel = member?.voice?.channel;

    if (commandName === 'play' && !voiceChannel)
        return interaction.reply({ content: '❌ Join a voice channel first!', ephemeral: true });

    await interaction.deferReply();

    try {
        if (commandName === 'play') {
            const query = interaction.options.getString('query');
            await interaction.editReply('🔍 Searching...');
            const track = await searchTrack(query);
            const entry = await getOrCreateEntry(guildId, voiceChannel, guild);
            entry.tracks.push(track);
            const isFirst = entry.tracks.length === 1;
            const embed   = new EmbedBuilder()
                .setColor('#9b59b6')
                .setAuthor({ name: isFirst ? '▶️ Now Playing' : '📋 Added to Queue' })
                .setTitle(track.title).setURL(track.url)
                .addFields(
                    { name: 'Artist',   value: track.author,                                 inline: true },
                    { name: 'Duration', value: track.duration,                               inline: true },
                    { name: 'Position', value: isFirst ? 'Now' : `#${entry.tracks.length}`, inline: true }
                );
            if (track.thumbnail) embed.setThumbnail(track.thumbnail);
            if (!entry.playing)  playNext(guildId);
            return interaction.editReply({ content: '', embeds: [embed] });
        }

        const entry = queues.get(guildId);

        if (commandName === 'skip') {
            if (!entry?.playing) return interaction.editReply('❌ Nothing is playing!');
            entry.player.stop();
            return interaction.editReply('⏭️ Skipped!');
        }
        if (commandName === 'pause') {
            if (!entry?.playing) return interaction.editReply('❌ Nothing is playing!');
            entry.player.pause();
            return interaction.editReply('⏸️ Paused!');
        }
        if (commandName === 'resume') {
            if (!entry) return interaction.editReply('❌ Nothing in queue!');
            entry.player.unpause();
            return interaction.editReply('▶️ Resumed!');
        }
        if (commandName === 'stop') {
            if (!entry) return interaction.editReply('❌ Nothing is playing!');
            entry.tracks = []; entry.player.stop(); entry.connection.destroy(); queues.delete(guildId);
            return interaction.editReply('⏹️ Stopped!');
        }
        if (commandName === 'volume') {
            if (!entry) return interaction.editReply('❌ Nothing is playing!');
            const vol = Math.max(1, Math.min(100, interaction.options.getInteger('amount')));
            entry.volume = vol / 100;
            return interaction.editReply(`🔊 Volume set to **${vol}%** (next song)`);
        }
        if (commandName === 'queue') {
            if (!entry || !entry.tracks.length) return interaction.editReply('❌ Queue is empty!');
            const list  = entry.tracks.map((t, i) => `${i === 0 ? '▶️' : `**${i}.**`} ${t.title} — \`${t.duration}\``).join('\n');
            const embed = new EmbedBuilder().setColor('#9b59b6').setTitle('📜 Queue').setDescription(list.substring(0, 2000)).setFooter({ text: `${entry.tracks.length} song(s)` });
            return interaction.editReply({ embeds: [embed] });
        }
        if (commandName === 'nowplaying') {
            if (!entry?.playing || !entry.tracks.length) return interaction.editReply('❌ Nothing is playing!');
            const track = entry.tracks[0];
            const embed = new EmbedBuilder().setColor('#9b59b6').setAuthor({ name: '▶️ Now Playing' })
                .setTitle(track.title).setURL(track.url)
                .addFields({ name: 'Artist', value: track.author, inline: true }, { name: 'Duration', value: track.duration, inline: true });
            if (track.thumbnail) embed.setThumbnail(track.thumbnail);
            return interaction.editReply({ embeds: [embed] });
        }

    } catch (e) {
        console.error('[Command Error]', e);
        return interaction.editReply(`❌ ${e.message?.substring(0, 200) || 'Unknown error'}`);
    }
});

client.login(process.env.DISCORD_TOKEN);
