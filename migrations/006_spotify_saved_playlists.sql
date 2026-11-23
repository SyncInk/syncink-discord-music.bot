-- 006_spotify_saved_playlists.sql
-- SyncInk Radio: Persistent Saved Spotify Public & Library Playlists

CREATE TABLE IF NOT EXISTS user_spotify_playlists (
    id SERIAL PRIMARY KEY,
    discord_user_id BIGINT NOT NULL,
    spotify_playlist_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    url TEXT NOT NULL,
    image_url TEXT,
    tracks_total INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(discord_user_id, spotify_playlist_id)
);

CREATE INDEX IF NOT EXISTS idx_spotify_playlists_user ON user_spotify_playlists(discord_user_id);
