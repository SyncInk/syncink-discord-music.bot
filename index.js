require('dotenv').config();
const { Client, GatewayIntentBits, REST, Routes } = require('discord.js');
// 1. ADDED QueryType HERE
const { Player, QueryType } = require('discord-player'); 

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildVoiceStates,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent
    ]
});

const player = new Player(client, {
    ytdlOptions: {
        quality: 'highestaudio',
        highWaterMark: 1 << 25
    }
});

const commands = [
    { name: 'play', description: 'Plays a track from a url or search term', options: [{ name: 'query', type: 3, description: 'Song to play', required: true }] }
];

client.once('ready', async () => {
    console.log(`📡 SyncInk Radio is online and logged in as ${client.user.tag}`);
    await player.extractors.loadDefault();
    const rest = new REST({ version: '10' }).setToken(process.env.DISCORD_TOKEN);
    await rest.put(Routes.applicationCommands(client.user.id), { body: commands });
    console.log('✅ Commands registered!');
});

player.events.on('error', (queue, error) => {
    console.log(`[Queue Error] ${error.message}`);
});
player.events.on('playerError', (queue, error) => {
    console.log(`[Audio Error] ${error.message}`);
});

client.on('interactionCreate', async interaction => {
    if (!interaction.isChatInputCommand()) return;
    const channel = interaction.member.voice.channel;
    
    if (!channel) return interaction.reply({ content: '❌ Join a voice channel first!', ephemeral: true });
    await interaction.deferReply();

    if (interaction.commandName === 'play') {
        const query = interaction.options.getString('query');
        try {
            const { track } = await player.play(channel, query, {
                nodeOptions: { metadata: interaction },
                // 2. FORCED YOUTUBE SEARCH HERE
                searchEngine: QueryType.YOUTUBE_SEARCH 
            });
            return interaction.followUp(`🎶 Enqueued **${track.title}**!`);
        } catch (e) {
            console.error(e);
            return interaction.followUp(`❌ Error playing track: ${e.message}`);
        }
    }
});

client.login(process.env.DISCORD_TOKEN);
