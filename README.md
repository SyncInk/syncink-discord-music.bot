# SyncInk Radio & Moderation Bot 🎵🛡️

High-fidelity Discord Radio, Music Playback, AI DJ AutoPlay, and Staff Moderation engine for the **SyncInk Ecosystem**.

Built with `discord.py`, native Opus hardware encoding, zero-buffer socket reconnections, and Discord Components V2 UI.

---

## 🌟 Key Features

### 🎧 Radio & Music Playback
* **48kHz Native Opus Streaming**: Hardware-aligned 48kHz stereo 192kbps playback with direct Opus container extraction (`bestaudio[ext=webm]`, Format 251) eliminating CPU resampling jitter.
* **Global 24/7 Live Radio**: Built-in worldwide radio directory browsing by country flags and station search.
* **Interactive Components V2 Player Card**: Real-time progress bar, dynamic thumbnail accessories, and 2-row button controls:
  * Row 1: `Previous`, `Pause/Resume`, `Next`, `Repeat`, `Stop`
  * Row 2: `Queue`, `Shuffle`, `Radio`
* **AI DJ & AutoPlay**: Intelligent multi-tiered recommendations (Gemini, OpenAI, Heuristic Clusters), hard language isolation, mood & genre preferences, and manual play taste learning.
* **Interactive Search**: `/search <query>` with multi-option interactive picker.

### 🛡️ Staff Moderation Suite
* **Full Disciplinary Suite**: `warn`, `timeout` / `mute`, `untimeout` / `unmute`, `kick`, `ban`, `unban`, and `purge` / `clear`.
* **Persistent Case Logging**: Automatically records every moderation case with timestamp, target, moderator, and reason into PostgreSQL or local SQLite.
* **Case History & Registry**: Inspect user infractions with `?modlogs @member` and full case records with `?case <id>`.
* **Disciplinary DM Alerts**: Automatically and safely notifies warned/timed-out members via direct message.
* **Security & Rate Limiting**: Progressive warning ladder for unauthorized command executions and flood protection.

---

## 🚀 Quick Start

### 1. Requirements
* Python 3.10+
* `ffmpeg` and `libopus` (Windows: bundled `ffmpeg.exe`; Linux/Termux: install via package manager)

### 2. Installation
```bash
git clone https://github.com/SyncInk/syncink-discord-music.bot.git
cd syncink-discord-music.bot
pip install -r requirements.txt
```

### 3. Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Fill in your `DISCORD_TOKEN`. `DATABASE_URL` is optional (defaults to `./data/syncink_radio.db`).

### 4. Running the Bot
* **Normal**: `python main.py`
* **Termux / Linux 24/7 Keepalive**: `./start.sh`
* **Docker**: `docker build -t syncinkradio . && docker run --env-file .env syncinkradio`

---

## 📜 Commands Reference

### Radio & Music (`/`)
* `/play <query>` - Play audio from YouTube, Spotify, or SoundCloud
* `/radio [country] [station]` - 24/7 live world radio streams
* `/lofi` - Instant 24/7 high-fidelity Lo-Fi beats
* `/autoplay` - Open AutoPlay Control Center
* `/queue` - View upcoming tracks with pagination
* `/nowplaying` (`/np`) - Real-time player card
* `/skip` - Skip current track
* `/previous` - Return to previous track
* `/pause` / `/resume` - Toggle pause
* `/stop` / `/leave` - Disconnect bot & clear queue
* `/volume <1-150>` - Adjust playback volume
* `/loop <off|track|queue>` - Repeat modes
* `/shuffle` - Shuffle queue
* `/search <query>` - Search top 5 results

### Moderation (`?` or `/`)
* `?warn <member> [reason]` - Issue warning & DM member
* `?timeout` / `?mute <member> <mins> [reason]` - Temporarily timeout member
* `?untimeout` / `?unmute <member> [reason]` - Remove member timeout
* `?kick <member> [reason]` - Kick member from server
* `?ban <member> [reason]` - Permanently ban member
* `?unban <user_id> [reason]` - Unban member by ID
* `?purge` / `?clear <1-100>` - Bulk delete messages
* `?modlogs [@member]` - View infractions or server registry
* `?case <case_id>` - View specific case details

---

## 📄 License
SyncInk Ecosystem © 2026. All rights reserved.
