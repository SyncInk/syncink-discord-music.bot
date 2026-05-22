require('dotenv').config();
const { Client, GatewayIntentBits, REST, Routes, EmbedBuilder } = require('discord.js');
const { Player } = require('discord-player');
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
const player = new Player(client);

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
    { name: 'skip', description: 'Skip to the next track or multiple tracks in queue', options: [{ name: 'amount', type: 4, description: 'Amount of tracks to skip', required: false }] },
    { name: 'volume', description: 'Adjusts the volume of the playback', options: [{ name: 'level', type: 4, description: 'Volume level (1-100)', required: true }] },
    { name: 'queue', description: 'Shows the queue', options: [{ name: 'list', type: 1, description: 'Shows the current queue for this server' }] },
    { name: 'remove', description: 'Removes a track from your queue', options: [{ name: 'track', type: 4, description: 'Track number to remove', required: true }] },
    { name: 'help', description: 'Lists all the commands' },
    { name: 'lyrics', description: 'Searches a track\'s lyrics' },
    { name: 'autoplay', description: 'Disables or enables the autoplay' },
    { name: 'pause', description: 'Pauses the playback of the player' },
    { name: 'replay', description: 'Replay the currently playing track' },
    { name: 'bassboost', description: 'Changes the bassboost settings on the player' },
    { name: '8d', description: 'Toggle the 8D audio filter on or off' },
    { name: 'resume', description: 'Resumes the playback of the player' },
    { name: 'np', description: 'Show information about the currently playing track' },
    { name: 'seek', description: 'Seek to a specific time in the currently playing track', options: [{ name: 'seconds', type: 4, description: 'Time in seconds', required: true }] },
    { name: 'previous', description: 'Goes back to the first track in listening history' }
];

client.once('ready', async () => {
    console.log(`📡 SyncInk Radio is online and logged in as ${client.user.tag}`);
    
    // Load high-quality audio extractors
    await player.extractors.loadMulti(DefaultExtractors);
    
    // Register the slash commands
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
                    }
                });

                // PROFESSIONAL UI EMBED FOR ADDING SONGS
                const embed = new EmbedBuilder()
                    .setColor('#9b59b6') // SyncInk Purple
                    .setAuthor({ name: '🎵 Added to Queue' })
                    .setTitle(track.title)
                    .setURL(track.url)
                    .setThumbnail(track.thumbnail)
                    .addFields(
                        { name: 'Channel / Artist', value: track.author || 'Unknown', inline: true },
                        { name: 'Duration', value: track.duration, inline: true },
                        { name: 'Source', value: track.source.charAt(0).toUpperCase() + track.source.slice(1), inline: true }
                    )
                    .setFooter({ text: `Requested by ${interaction.user.username}`, iconURL: interaction.user.displayAvatarURL() });

                return interaction.followUp({ embeds: [embed] });
            } catch (e) {
                return interaction.followUp(`❌ | Error playing track: ${e.message}`);
            }
        }
        
        case 'shuffle': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            queue.tracks.shuffle();
            return interaction.followUp('🔀 | Queue successfully shuffled!');
        }

        case 'loop': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            const mode = interaction.options.getSubcommand();
            if (mode === 'all') queue.setRepeatMode(2); 
            if (mode === 'current') queue.setRepeatMode(1); 
            if (mode === 'disable') queue.setRepeatMode(0); 
            return interaction.followUp(`🔁 | Loop mode changed to **${mode}**!`);
        }

        case 'skip': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            const amount = interaction.options.getInteger('amount') || 1;
            for (let i = 0; i < amount; i++) queue.node.skip();
            return interaction.followUp(`⏭️ | Skipped **${amount}** track(s)!`);
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

        case 'remove': {
            if (!queue || queue.tracks.data.length === 0) return interaction.followUp('❌ | The queue is empty.');
            const index = interaction.options.getInteger('track') - 1;
            if (!queue.tracks.data[index]) return interaction.followUp('❌ | Invalid track number.');
            const trackName = queue.tracks.data[index].title;
            queue.removeTrack(index);
            return interaction.followUp(`🗑️ | Removed **${trackName}** from the queue.`);
        }

        case 'help': {
            return interaction.followUp(`**🎧 SyncInk Radio Commands:**
\`/play <query>\` - Play from URL or search term
\`/search <query>\` - Search supported platforms
\`/shuffle\` - Shuffle queue
\`/loop [all/current/disable]\` - Change loop state
\`/skip [amount]\` - Skip tracks
\`/volume <1-100>\` - Adjust volume
\`/queue list\` - View upcoming songs
\`/remove <number>\` - Remove a song
\`/lyrics\` - Display song lyrics
\`/autoplay\` - Toggle continuous autoplay
\`/pause\` & \`/resume\` - Playback controls
\`/replay\` - Restart the current track
\`/bassboost\` & \`/8d\` - Toggle high-quality audio filters
\`/np\` - Now Playing info
\`/seek <seconds>\` - Jump to timeframe
\`/previous\` - Play last track`);
        }

        case 'lyrics': {
            if (!queue || !queue.currentTrack) return interaction.followUp('❌ | Nothing is playing right now.');
            const trackTitle = queue.currentTrack.title;
            return interaction.followUp(`📝 | Searching for lyrics for **${trackTitle}**... *(Note: SyncInk Radio uses an external web engine for lyrics).*`);
        }

        case 'autoplay': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            const isAutoplay = queue.repeatMode === 3;
            queue.setRepeatMode(isAutoplay ? 0 : 3);
            return interaction.followUp(`🤖 | Autoplay has been **${isAutoplay ? 'Disabled' : 'Enabled'}**!`);
        }

        case 'pause': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            queue.node.setPaused(true);
            return interaction.followUp('⏸️ | Playback paused!');
        }

        case 'replay': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            queue.node.seek(0);
            return interaction.followUp('⏪ | Replaying the current track!');
        }

        case 'bassboost': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            await queue.filters.ffmpeg.toggle('bassboost');
            const status = queue.filters.ffmpeg.filters.includes('bassboost') ? 'Enabled' : 'Disabled';
            return interaction.followUp(`🎸 | Bassboost **${status}**! *(Changes may take a few seconds to apply)*`);
        }

        case '8d': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            await queue.filters.ffmpeg.toggle('8D');
            const status = queue.filters.ffmpeg.filters.includes('8D') ? 'Enabled' : 'Disabled';
            return interaction.followUp(`🎧 | 8D Audio Filter **${status}**! *(Changes may take a few seconds to apply)*`);
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

            // PROFESSIONAL UI EMBED FOR NOW PLAYING
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

        case 'seek': {
            if (!queue || !queue.isPlaying()) return interaction.followUp('❌ | Nothing is playing right now.');
            const time = interaction.options.getInteger('seconds') * 1000;
            queue.node.seek(time);
            return interaction.followUp(`⏩ | Seeked playback to **${interaction.options.getInteger('seconds')}s**!`);
        }

        case 'previous': {
            const history = player.nodes.get(interaction.guildId)?.history;
            if (!history || history.isEmpty()) return interaction.followUp('❌ | There is no previous track in your listening history.');
            await history.previous();
            return interaction.followUp('⏮️ | Now playing the previous track!');
        }
    }
});

client.login(process.env.DISCORD_TOKEN);