# Run SyncInk Radio in Termux

## Install

In Termux, install a supported Node.js runtime and FFmpeg:

```sh
pkg update
pkg install nodejs-lts ffmpeg
```

From the bot directory, install the locked dependencies and configure the bot:

```sh
npm ci
cp .env.example .env
```

Set `DISCORD_TOKEN` and `DISCORD_CLIENT_ID` in `.env`. Set `FFMPEG_PATH` to:

```text
/data/data/com.termux/files/usr/bin/ffmpeg
```

To enable AI-ranked autoplay, add your own `OPENAI_API_KEY` to `.env`. `OPENAI_MODEL` defaults to `gpt-6-astra`; the bot makes a recommendation request at most once every ten minutes per opted-in user. The key stays on the device and is never committed.

Then start the bot with `npm start`. Keep the Termux session alive and allow Termux to run without Android battery optimization if you want long sessions. Android can still suspend or stop background processes, and network or host-side interruptions can interrupt playback; a phone cannot guarantee uninterrupted 24/7 service by itself.

For longer sessions, keep Android battery optimization disabled for Termux and run `termux-wake-lock` in the Termux session before `npm start`. Use `termux-wake-unlock` when you stop the bot. Device makers may also have a separate background-app setting for Termux.

Normal playback passes through the source Opus audio at 100% without an added decode, gain stage, or re-encode when the extractor provides a supported Opus stream. This preserves the source audio and reduces CPU use on phones. Explicitly changing `/volume` or enabling FFmpeg effects such as bass boost, 8D, nightcore, or vaporwave opts that queue into extra processing. `/seek` and replay can also restart the source stream. Keep the bot and Termux updated, use a stable Wi-Fi connection, and avoid running other heavy jobs on the phone during long playback.

Radio stations search for short tracks, keep a multi-track queue filled, and avoid recent repeats. Autoplay is on by default for regular queues; use `/autoplay mode:off` to stop when the queue ends. If you already have an older `.env`, set `DEFAULT_AUTOPLAY=true` there to keep this default after updating. If a stream fails, the bot tries to replace it without skipping a healthy next track. `/taste mode:on` opts in to local per-server taste learning from liked or mostly completed tracks; `/taste mode:off` pauses it and `/taste mode:forget` deletes the profile. When AI is configured, only that opted-in user's taste summary and song metadata are sent for ranking, without Discord IDs or usernames. The `/247` mode keeps the voice session connected while the voice channel is empty; `/247 mode:off`, `/stop`, and `/leave` end continuous playback.

## Custom platform emojis

Download the platform and control emoji assets you want from emoji.gg, upload them to your Discord server, and give the bot permission to use them. Copy each Discord emoji token (for example, `<:youtube:123456789012345678>`) into the matching `EMOJI_*` variable in `.env`. Supported variables are `EMOJI_YOUTUBE`, `EMOJI_YOUTUBE_MUSIC`, `EMOJI_SOUNDCLOUD`, `EMOJI_SPOTIFY`, `EMOJI_APPLE_MUSIC`, `EMOJI_DEEZER`, `EMOJI_TIDAL`, `EMOJI_DIRECT_AUDIO`, `EMOJI_PAUSE_RESUME`, `EMOJI_SKIP`, `EMOJI_STOP`, `EMOJI_LIKE`, and `EMOJI_PLAYLIST`. The now-playing card and buttons fall back to standard emoji when an optional token is blank or invalid. A token must refer to an emoji the bot can use in that server; an emoji.gg page URL alone cannot be rendered as a Discord custom emoji.
