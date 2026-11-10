-- 003_dashboard_and_analytics.sql
-- SyncInk Radio: Dashboard sessions, library favorites, listening history, and guild settings

CREATE TABLE IF NOT EXISTS user_sessions (
    session_id TEXT PRIMARY KEY,
    discord_user_id BIGINT NOT NULL,
    username TEXT,
    discriminator TEXT,
    avatar TEXT,
    access_token TEXT,
    refresh_token TEXT,
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_favorites (
    id SERIAL PRIMARY KEY,
    discord_user_id BIGINT NOT NULL,
    item_type TEXT NOT NULL,
    item_id TEXT NOT NULL,
    title TEXT NOT NULL,
    subtitle TEXT,
    image_url TEXT,
    url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(discord_user_id, item_type, item_id)
);

CREATE TABLE IF NOT EXISTS listening_history (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT,
    discord_user_id BIGINT,
    track_title TEXT NOT NULL,
    track_author TEXT,
    track_url TEXT,
    duration INTEGER DEFAULT 0,
    platform TEXT DEFAULT 'youtube',
    thumbnail_url TEXT,
    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_history_user ON listening_history(discord_user_id);
CREATE INDEX IF NOT EXISTS idx_history_played_at ON listening_history(played_at);
CREATE INDEX IF NOT EXISTS idx_history_guild ON listening_history(guild_id);
CREATE INDEX IF NOT EXISTS idx_favorites_user ON user_favorites(discord_user_id);
