# SyncInk Radio Bot 🎵📻

High-fidelity Discord Radio, Music Playback, and AI DJ AutoPlay engine for the **SyncInk Ecosystem**.

Built with `discord.py`, native Opus hardware encoding, zero-buffer socket reconnections, and Discord Components V2 UI.

---

## 🌟 Key Features

* **48kHz Native Opus Streaming**: Hardware-aligned 48kHz stereo 192kbps playback with direct Opus container extraction (`bestaudio[ext=webm]`, Format 251) eliminating CPU resampling jitter.
* **Global 24/7 Live Radio**: Built-in worldwide radio directory browsing by country flags and station search.
* **Interactive Components V2 Player Card**: Real-time progress bar, dynamic thumbnail accessories, and 2-row button controls using authentic custom server emojis:
  * **Row 1**: `Previous`, `Pause/Resume`, `Next`, `Repeat`, `Stop`
  * **Row 2**: `Queue`, `Shuffle`, `Radio`
* **AI DJ & AutoPlay**: Intelligent multi-tiered recommendations (Gemini, OpenAI, Heuristic Clusters), hard language isolation, mood & genre preferences, and manual play taste learning.
* **Interactive Search**: `/search <query>` with multi-option interactive picker.
* **Dual Database Persistence**: Automatic local SQLite storage (`./data/syncink_radio.db`) or optional cloud PostgreSQL.

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
Fill in your `DISCORD_TOKEN`.

### 4. Running the Bot
* **Normal**: `python main.py`
* **Termux / Linux 24/7 Keepalive**: `./start.sh`
* **Docker**: `docker build -t syncinkradio . && docker run --env-file .env syncinkradio`

---

## 📜 Commands Reference

### Playback & Streaming (`/` or `?`)
* `/play <query>` - Play audio from YouTube, Spotify, or SoundCloud
* `/search <query>` - Search and select from top 5 audio results
* `/pause` / `/resume` - Toggle pause
* `/skip` - Skip current track
* `/previous` - Return to previous track
* `/replay` - Restart current track
* `/stop` / `/leave` - Disconnect bot & clear queue

### Queue & Sound Controls
* `/queue` - View upcoming tracks with interactive pagination
* `/nowplaying` (`/np`) - Real-time player card with progress bar
* `/volume <1-150>` - Adjust playback volume
* `/loop <off|track|queue>` - Repeat modes
* `/shuffle` - Randomly shuffle queue

### 24/7 Global Radio & AI AutoPlay
* `/radio [country] [station]` - Stream live world radio stations
* `/lofi` - Instant 24/7 high-fidelity Lo-Fi beats
* `/autoplay` - Open AutoPlay Control Center with genre/language preferences

---

## 📄 License
SyncInk Ecosystem © 2026. All rights reserved.
