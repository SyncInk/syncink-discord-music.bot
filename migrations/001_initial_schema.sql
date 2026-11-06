-- 001_initial_schema.sql
-- SyncInk Radio & Moderation initial schema

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id BIGINT PRIMARY KEY,
    welcome_channel_id BIGINT,
    log_channel_id BIGINT,
    autorole_id BIGINT,
    log_channel_moderation BIGINT,
    automod_log_channel_id BIGINT,
    music_channel_id BIGINT,
    dj_role_id BIGINT
);

CREATE TABLE IF NOT EXISTS mod_cases (
    case_id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    mod_id BIGINT NOT NULL,
    action VARCHAR(50) NOT NULL,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
