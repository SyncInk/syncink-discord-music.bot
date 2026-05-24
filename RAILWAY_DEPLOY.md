# SyncInk Radio - Railway Deploy Notes

## Required environment variables
- `DISCORD_TOKEN`
- `DISCORD_CLIENT_ID`
- `DISCORD_GUILD_ID` (optional, recommended for instant guild command updates)
- `DATA_DIR` (set to `/data` when using a Railway volume)
- `DEFAULT_AUTOPLAY` (`true` or `false`)

## Railway setup
1. Keep the start command as: `npm run start`
2. Add a persistent volume in Railway and mount it to `/data`
3. Set `DATA_DIR=/data` so liked playlists survive redeploys
4. Redeploy after pushing this code to GitHub

## Slash command sync
- If `DISCORD_GUILD_ID` is set, commands update in that server almost instantly.
- If not set, commands register globally and can take up to about 1 hour.

## Main slash commands
- `/play query:<song name or link> platform:<optional>`
- `/search query:<song name> platform:<optional>`
- `/queue list`
- `/queue clear`
- `/shuffle`
- `/loop mode:<all|current|disable>`
- `/skip count:<optional>`
- `/volume percent:<0-200>`
- `/remove position:<number>`
- `/help`
- `/lyrics query:<optional>`
- `/autoplay mode:<on|off>`
- `/pause`
- `/resume`
- `/replay`
- `/bassboost mode:<off|low|normal|high>`
- `/8d mode:<on|off>`
- `/seek position:<90|1:30|00:01:30|2m>`
- `/previous`
- `/np`
- `/stop`
- `/leave`
- `/playlist show|play|remove|clear`

## Buttons in now playing card
- Pause/Resume
- Skip
- Stop
- Like
- Playlist
