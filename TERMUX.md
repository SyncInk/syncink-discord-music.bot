# Running SyncInk Radio on Termux (Android)

SyncInk Radio is powered by a high-fidelity Python Discord engine with native Opus C-library binding, DAVE protocol fallback shimming, and 48kHz audio alignment.

## 1. Install Required Termux Packages

Open Termux and run:
```bash
pkg update && pkg upgrade -y
pkg install -y python python-pillow ffmpeg libopus libsodium clang make python-dev libffi git
```

## 2. Clone / Pull Bot Repository

```bash
git clone https://github.com/SyncInk/syncink-discord-music.bot.git SyncInkRadio
cd SyncInkRadio
```

## 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

## 4. Configure Environment

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
nano .env
```
Fill in your `DISCORD_TOKEN`. (You can leave `DATABASE_URL` empty to automatically use the built-in SQLite database).

## 5. Keepalive & Auto-Restart

To run 24/7 with automatic wake-lock and auto-restart on network hiccups:
```bash
chmod +x start.sh
./start.sh
```

To stop the runner, press `Ctrl+C`.
