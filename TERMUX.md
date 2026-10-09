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

Radio stations search for genre-matched tracks, keep a multi-track queue filled, and avoid recent repeats. Player progress refresh defaults to once every 15 seconds (configurable with `NOW_PLAYING_REFRESH_MS`, bounded from 10 to 60 seconds), and edits are serialized globally to limit Discord API pressure. Autoplay is on by default for regular queues; use `/autoplay mode:off` to stop when the queue ends. If you already have an older `.env`, set `DEFAULT_AUTOPLAY=true` there to keep this default after updating. If a stream fails, the bot tries to replace it without skipping a healthy next track. `/taste mode:on` opts in to local per-server taste learning from liked or mostly completed tracks; `/taste mode:off` pauses it and `/taste mode:forget` deletes the profile. When AI is configured, only that opted-in user's taste summary and song metadata are sent for ranking, without Discord IDs or usernames. The `/247` mode keeps the voice session connected while the voice channel is empty; `/247 mode:off`, `/stop`, and `/leave` end continuous playback.

## Custom platform emojis

The player card uses the custom platform and control emoji IDs shown in SyncInk Radio's server. It falls back to standard emoji when the bot cannot resolve an uploaded emoji. To use those icons in another server, invite the bot to the emoji's home server too, or upload the emojis in the destination server and set the matching `EMOJI_*` token in `.env`. An emoji.gg page URL alone cannot be rendered as a Discord custom emoji.

## Install the bot in another server

Run `/invite` in any server where the bot is already present and open the private install link from an account with **Manage Server** permission in the destination. If Discord does not offer a server selector or the install completes without adding the bot, open the Discord Developer Portal for this application. Under **Bot**, enable **Public Bot**. Under **Installation**, enable **Guild Install** and configure the install link with the `bot` and `applications.commands` scopes. Also confirm the bot has the `Connect`, `Speak`, `Send Messages`, `Embed Links`, and `Use External Emojis` permissions. Guild slash commands are registered globally and are available after Discord propagates them; `DISCORD_GUILD_ID` additionally enables immediate registration in one development server.

## Music source notes

YouTube, YouTube Music, SoundCloud, Spotify, and Apple Music have search/link extractors in the current player. Spotify and Apple Music provide catalog metadata and resolve playback through a supported stream source; this bot cannot stream their protected audio directly. Deezer and TIDAL links are title-resolved and searched through a supported stream source; the bot does not claim their direct audio. Auto search prioritizes YouTube search and falls back through other supported sources. Search and radio remove obvious short-form clips, edits, slowed/sped-up versions, covers, and cross-source duplicate song titles unless the request explicitly asks for that version. Upload metadata cannot prove a release is official, so the bot does not label an arbitrary upload as verified official.
