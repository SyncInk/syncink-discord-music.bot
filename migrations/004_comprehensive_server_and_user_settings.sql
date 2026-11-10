-- 004_comprehensive_server_and_user_settings.sql
-- SyncInk Radio: Comprehensive Guild Settings, User Preferences, and Custom Playlists

-- 1. Extend Guild Settings with comprehensive controls
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS default_voice_channel_id BIGINT;
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS max_volume INTEGER DEFAULT 100;
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS autoplay_enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS is_247 BOOLEAN DEFAULT FALSE;
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS announcements_enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS playback_notifications BOOLEAN DEFAULT TRUE;
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS server_language TEXT DEFAULT 'en';
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS preferred_radio_country TEXT DEFAULT 'India';
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS audia_genre TEXT;
ALTER TABLE guild_settings ADD COLUMN IF NOT EXISTS audia_mood TEXT;

-- 2. User Preferences (Timezone, Language, Privacy, Theme)
CREATE TABLE IF NOT EXISTS user_preferences (
    discord_user_id BIGINT PRIMARY KEY,
    timezone TEXT DEFAULT 'UTC',
    language TEXT DEFAULT 'en',
    private_listening BOOLEAN DEFAULT FALSE,
    theme TEXT DEFAULT 'dark',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Custom User Playlists
CREATE TABLE IF NOT EXISTS user_playlists (
    id SERIAL PRIMARY KEY,
    discord_user_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_playlist_tracks (
    id SERIAL PRIMARY KEY,
    playlist_id INTEGER NOT NULL REFERENCES user_playlists(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    author TEXT,
    url TEXT NOT NULL,
    duration INTEGER DEFAULT 0,
    thumbnail TEXT,
    platform TEXT DEFAULT 'youtube',
    position INTEGER DEFAULT 0,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_playlists_user ON user_playlists(discord_user_id);
CREATE INDEX IF NOT EXISTS idx_playlist_tracks ON user_playlist_tracks(playlist_id);
