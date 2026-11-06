import os
import sys
from utils.logger import log

def validate_environment():
    """Validates required environment variables before startup."""
    log.info("Starting environment validation...")
    
    token = os.getenv("DISCORD_TOKEN")
    if not token or token.strip() in ("", "your_discord_bot_token_here"):
        log.critical("Missing required environment variable: DISCORD_TOKEN")
        log.critical("Please set DISCORD_TOKEN in your .env file or host environment.")
        sys.exit(1)
        
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        log.info("Database URL configured: Using external database.")
    else:
        log.info("DATABASE_URL not set: Using built-in local SQLite persistence (./data/syncink_radio.db).")
        
    log.info("Environment validation passed.")
