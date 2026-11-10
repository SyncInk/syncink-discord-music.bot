-- 002_spotify_integrations.sql
-- SyncInk Radio: Spotify Account Linking & OAuth Token Storage

CREATE TABLE IF NOT EXISTS spotify_users (
    discord_user_id BIGINT PRIMARY KEY,
    spotify_user_id TEXT,
    display_name TEXT,
    email TEXT,
    encrypted_refresh_token TEXT,
    scope TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS spotify_oauth_states (
    state TEXT PRIMARY KEY,
    discord_user_id BIGINT NOT NULL,
    code_verifier TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
