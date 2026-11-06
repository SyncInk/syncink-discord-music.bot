-- 001_initial_schema.sql
-- SyncInk Radio initial schema

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id BIGINT PRIMARY KEY,
    music_channel_id BIGINT,
    dj_role_id BIGINT
);
