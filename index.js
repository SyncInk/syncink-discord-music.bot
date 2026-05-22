require('dotenv').config();
const { Client, GatewayIntentBits, REST, Routes, EmbedBuilder } = require('discord.js');
const { Player, QueryType } = require('discord-player');
const { DefaultExtractors } = require('@discord-player/extractor');

// Initialize the Discord Client
const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildVoiceStates,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent
    ]
});

// Initialize the Audio Player
const player = new Player(client, {
    ytdlOptions: {
        quality: 'highestaudio',
        highWaterMark: 1 << 25
    }
});

// Defines the slash commands
const commands = [
    { name: 'play', description: 'Plays a track from a url or search term', options: [{ name: 'query', type: 3, description: 'Song to play', required: true }] },
    { name: 'search', description: 'Searches a track from supported platforms', options: [{ name: 'query', type: 3, description: 'Song to search', required: true }] },
    { name: 'shuffle', description: 'Shuffle the queue' },
    { name: 'loop', description: 'Loop modes', options: [
        { name: 'all', type: 1, description: 'Loops the whole queue' },
        { name: 'current', type: 1, description: 'Loops the current track' },
        { name: 'disable', type: 1, description: 'Disables the loop mode for this playback' }
    ]},
    { name: 'skip', description: 'Skip to the next track', options: [{ name: 'amount', type: 4, description: 'Amount of tracks to skip', required: false }] },
    { name: 'volume', description: 'Adjusts the volume', options: [{ name: 'level', type: 4, description: 'Volume level (1-100)', required: true }] },
    { name: 'queue', description: 'Shows the queue', options: [{ name: 'list', type: 1, description: 'Shows the current queue' }] },
    { name: 'remove', description: 'Removes a track', options: [{ name: 'track', type: 4, description: 'Track number', required: true }] },
    { name: 'help', description: 'Lists all the commands' },
    { name: 'pause', description: 'Pauses the playback' },
    { name: 'resume', description: 'Resumes the playback' },
    { name: 'np', description: 'Now playing info' }
];

client.once('ready', async () => {
    console.log(`📡 SyncInk Radio is online and logged in as ${client.user.tag}`);
    await player.extractors.loadDefault();
    
    const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
    try {
        await rest.put(Routes.applicationCommands(client.user.id), { body: commands });
        console.log('✅ Successfully registered all slash commands!');
    } catch (error) {
        console.error('❌ Failed to register commands:', error);
    }
});

client.on('interactionCreate', async interaction => {
    if (!interaction.isChatInputCommand()) return;
    
    const channel = interaction.member.voice.channel;
    if (interaction.commandName !== 'help' && !channel) {
        return interaction.reply({ content: '❌ You must be in a voice channel to use this command.', ephemeral: true });
    }

    await interaction.deferReply();
    const queue = player.nodes.get(interaction.guildId);

    switch (interaction.commandName) {
        case 'play':
        case 'search': {
            const query = interaction.options.getString('query');
            try {
                const { track } = await player.play(channel, query, {
                    nodeOptions: {
                        metadata: interaction,
                        leaveOnEmpty: true,
                        leaveOnEnd: false
                    },
                    // THIS IS THE FIX: Forcing YouTube to bypass Spotify blocks
                    searchEngine: QueryType.YOUTUBE_SEARCH
                });

                // PROFESSIONAL UI EMBED
                const embed = new EmbedBuilder()
                    .setColor('#9b59b6') 
                    .setAuthor({ name: '🎵 Added to Queue' })
                    .setTitle(track.title)
                    .setURL(track.url)
                    .setThumbnail(track.thumbnail)
                    .addFields(
                        { name: 'Channel / Artist', value: track.author || 'Unknown', inline: true },
                        { name: 'Duration', value: track.duration, inline: true }
                    )
                    .setFooter({ text: `Requested by ${interaction.user.username}`, iconURL: interaction.user.displayAvatarURL() });

                return interaction.followUp({ embeds: [embed] });
            } catch (e) {
                console.log(e);
                return interaction.followUp(`❌ | Error playing track. Please try a different song or URL.`);
            }
        }
        
        case 'skip': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            queue.node.skip();
            return interaction.followUp(`⏭️ | Skipped the track!`);
        }

        case 'volume': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            const level = interaction.options.getInteger('level');
            queue.node.setVolume(level);
            return interaction.followUp(`🔊 | Volume set to **${level}%**!`);
        }

        case 'queue': {
            if (!queue || queue.tracks.data.length === 0) return interaction.followUp('❌ | The queue is empty.');
            const tracks = queue.tracks.data.map((track, i) => `**${i + 1}.** [${track.title}](${track.url}) - ${track.author}`);
            
            const queueEmbed = new EmbedBuilder()
                .setColor('#9b59b6')
                .setTitle('📜 Server Queue')
                .setDescription(tracks.join('\n').substring(0, 4000));
            
            return interaction.followUp({ embeds: [queueEmbed] });
        }

        case 'pause': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            queue.node.setPaused(true);
            return interaction.followUp('⏸️ | Playback paused!');
        }

        case 'resume': {
            if (!queue) return interaction.followUp('❌ | No music is currently in the queue.');
            queue.node.setPaused(false);
            return interaction.followUp('▶️ | Playback resumed!');
        }

        case 'np': {
            if (!queue || !queue.currentTrack) return interaction.followUp('❌ | Nothing is playing right now.');
            const track = queue.currentTrack;
            const progress = queue.node.createProgressBar();

            const npEmbed = new EmbedBuilder()
                .setColor('#9b59b6')
                .setAuthor({ name: '🎧 Now Playing' })
                .setTitle(track.title)
                .setURL(track.url)
                .setThumbnail(track.thumbnail)
                .setDescription(`**Artist:** ${track.author}\n\n${progress}`)
                .setFooter({ text: `SyncInk Radio`, iconURL: client.user.displayAvatarURL() });

            return interaction.followUp({ embeds: [npEmbed] });
        }

        case 'help': {
            return interaction.followUp(`**🎧 SyncInk Radio Commands:**
\`/play <query>\` - Play from URL or search term
\`/skip\` - Skip tracks
\`/volume <1-100>\` - Adjust volume
\`/queue list\` - View upcoming songs
\`/pause\` & \`/resume\` - Playback controls
\`/np\` - Now Playing info`);
        }
    }
});

client.login(process.env.DISCORD_TOKEN);
