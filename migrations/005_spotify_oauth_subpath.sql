-- 005_spotify_oauth_subpath.sql
-- Ensure redirect_uri and return_to columns exist on spotify_oauth_states
ALTER TABLE spotify_oauth_states ADD COLUMN IF NOT EXISTS redirect_uri TEXT;
ALTER TABLE spotify_oauth_states ADD COLUMN IF NOT EXISTS return_to TEXT DEFAULT 'discord';
