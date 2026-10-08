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

The player uses the source stream without an added FFmpeg re-encode by default. Filters such as bass boost or 8D may use additional processing. Radio stations search for short tracks, fill a queue in batches, and avoid recent repeats. `/taste mode:on` opts in to local per-server taste learning from liked or mostly completed tracks; `/taste mode:off` pauses it and `/taste mode:forget` deletes the profile. When AI is configured, only that opted-in user's taste summary and song metadata are sent for ranking, without Discord IDs or usernames. The `/247` mode keeps the voice session connected while the voice channel is empty; `/247 mode:off`, `/stop`, and `/leave` end continuous playback.
