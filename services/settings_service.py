from database import db
from typing import Optional, Dict, Any
from services.cache_service import CacheService

class SettingsService:
    """Service layer for guild radio & music configuration."""
    
    @staticmethod
    async def get_guild_settings(guild_id: int) -> Dict[str, Any]:
        """Fetches settings for a guild, returning a dictionary. Uses cache."""
        cache_key = f"guild_settings_{guild_id}"
        cached = await CacheService.get(cache_key)
        if cached:
            return cached
            
        record = await db.fetchrow("SELECT * FROM guild_settings WHERE guild_id = $1", guild_id)
        if not record:
            await db.execute("INSERT INTO guild_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING", guild_id)
            record = await db.fetchrow("SELECT * FROM guild_settings WHERE guild_id = $1", guild_id)
            
        settings_dict = dict(record) if record else {}
        await CacheService.set(cache_key, settings_dict, expire_seconds=30)
        return settings_dict

    @staticmethod
    async def update_setting(guild_id: int, key: str, value: Any) -> bool:
        """Updates a specific setting for a guild and invalidates the cache."""
        allowed_keys = ["music_channel_id", "dj_role_id"]
        if key not in allowed_keys:
            raise ValueError(f"Invalid setting key: {key}")
            
        await db.execute(
            f"INSERT INTO guild_settings (guild_id, {key}) VALUES ($1, $2) "
            f"ON CONFLICT (guild_id) DO UPDATE SET {key} = $2;",
            guild_id, value
        )
        
        await CacheService.delete(f"guild_settings_{guild_id}")
        return True
