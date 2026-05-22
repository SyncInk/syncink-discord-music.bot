require('dotenv').config();
const { Client, GatewayIntentBits, REST, Routes, EmbedBuilder } = require('discord.js');
const { Player } = require('discord-player');
const { YoutubeiExtractor } = require('discord-player-youtubei');

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildVoiceStates,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent
    ]
});

const player = new Player(client);

player.events.on('error', (queue, error) => {
    console.log(`[Queue Error] ${error.message}`);
});

player.events.on('playerError', (queue, error) => {
    console.log(`[Audio Stream Error] ${error.message}`);
});

const commands = [
    { name: 'play', description: 'Plays a track from a url or search term', options: [{ name: 'query', type: 3, description: 'Song to play', required: true }] },
    { name: 'skip', description: 'Skip the current track' },
    { name: 'pause', description: 'Pause the music' },
    { name: 'resume', description: 'Resume the music' },
    { name: 'volume', description: 'Change volume', options: [{ name: 'amount', type: 4, description: 'Volume 1-100', required: true }] },
    { name: 'queue', description: 'Show the queue' }
];

client.once('ready', async () => {
    console.log(`📡 SyncInk Radio is online and logged in as ${client.user.tag}`);

    await player.extractors.register(YoutubeiExtractor, {});
    console.log('✅ YoutubeiExtractor loaded!');

    const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
    await rest.put(Routes.applicationCommands(client.user.id), { body: commands });
    console.log('✅ Commands registered!');
});

client.on('interactionCreate', async interaction => {
    if (!interaction.isChatInputCommand()) return;

    const channel = interaction.member.voice.channel;
    if (!channel) return interaction.reply({ content: '❌ Join a voice channel first!', ephemeral: true });

    await interaction.deferReply();
    const queue = player.nodes.get(interaction.guildId);

    try {
        if (interaction.commandName === 'play') {
            const query = interaction.options.getString('query');

            const { track } = await player.play(channel, query, {
                nodeOptions: {
                    metadata: interaction,
                    leaveOnEmpty: true,
                    leaveOnEnd: false,
                    volume: 80
                }
            });

            const embed = new EmbedBuilder()
                .setColor('#9b59b6')
                .setAuthor({ name: '🎵 Added to Queue' })
                .setTitle(track.title)
                .setURL(track.url)
                .setThumbnail(track.thumbnail)
                .addFields(
                    { name: 'Artist', value: track.author || 'Unknown', inline: true },
                    { name: 'Duration', value: track.duration, inline: true }
                );

            return interaction.followUp({ embeds: [embed] });
        }

        if (interaction.commandName === 'skip') {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ Nothing is playing!');
            queue.node.skip();
            return interaction.followUp('⏭️ Skipped!');
        }

        if (interaction.commandName === 'pause') {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ Nothing is playing!');
            queue.node.setPaused(true);
            return interaction.followUp('⏸️ Paused!');
        }

        if (interaction.commandName === 'resume') {
            if (!queue) return interaction.followUp('❌ Nothing is playing!');
            queue.node.setPaused(false);
            return interaction.followUp('▶️ Resumed!');
        }

        if (interaction.commandName === 'volume') {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ Nothing is playing!');
            const vol = interaction.options.getInteger('amount');
            queue.node.setVolume(vol);
            return interaction.followUp(`🔊 Volume set to ${vol}%`);
        }

        if (interaction.commandName === 'queue') {
            if (!queue || queue.tracks.data.length === 0) return interaction.followUp('❌ Queue is empty.');
            const tracks = queue.tracks.data.map((t, i) => `**${i + 1}.** ${t.title}`);
            const qEmbed = new EmbedBuilder()
                .setColor('#9b59b6')
                .setTitle('📜 Queue')
                .setDescription(tracks.join('\n').substring(0, 2000));
            return interaction.followUp({ embeds: [qEmbed] });
        }

    } catch (e) {
        console.log(`[Command Error]: ${e}`);
        return interaction.followUp('❌ An error occurred. Try a different track.');
    }
});

client.login(process.env.DISCORD_TOKEN);
