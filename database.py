import asyncio
import os
import re
import sqlite3
from typing import Any, List, Optional, Dict
from utils.logger import log
from utils.exceptions import DatabaseError

try:
    import asyncpg
except ImportError:
    asyncpg = None

def _redact_sensitive(text: str) -> str:
    """Redacts credentials from database connection strings and logs."""
    if not text:
        return ""
    return re.sub(r'(postgres(?:ql)?://[^:]+:)([^@]+)(@)', r'\1***REDACTED***\3', str(text))

class SQLiteRecord(dict):
    """Dict subclass providing both dict item and attribute-like or index access to mimic asyncpg.Record."""
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)

class DatabaseManager:
    def __init__(self):
        self.is_postgres = False
        self.pool: Optional[Any] = None
        self._sqlite_conn: Optional[sqlite3.Connection] = None
        self._lock: Optional[asyncio.Lock] = None

    def is_connected(self) -> bool:
        if self.is_postgres:
            return (
                self.pool is not None and 
                not getattr(self.pool, '_closed', False) and 
                not getattr(self.pool, '_closing', False)
            )
        return self._sqlite_conn is not None

    async def ensure_connected(self):
        if self.is_connected():
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if not self.is_connected():
                await self.connect()

    async def connect(self):
        dsn = os.getenv("DATABASE_URL")
        
        # 1. PostgreSQL Backend (if DATABASE_URL is set to postgres)
        if dsn and (dsn.startswith("postgres://") or dsn.startswith("postgresql://")):
            if asyncpg is None:
                raise DatabaseError("asyncpg is required to connect to PostgreSQL. Please install asyncpg.")
            self.is_postgres = True
            
            ssl_ctx = "require"
            if "127.0.0.1" in dsn or "localhost" in dsn or "sslmode=disable" in dsn.lower():
                ssl_ctx = False
                
            try:
                if self.pool and not getattr(self.pool, '_closed', False):
                    try:
                        await self.pool.close()
                    except Exception:
                        pass
                pool_kwargs = {"dsn": dsn, "command_timeout": 60, "ssl": ssl_ctx}
                if "6543" in dsn or "pgbouncer" in dsn.lower():
                    pool_kwargs["statement_cache_size"] = 0
                self.pool = await asyncpg.create_pool(**pool_kwargs)
                log.info("Successfully connected to the PostgreSQL database.")
                
                from migrations import MigrationManager
                migration_manager = MigrationManager(self.pool)
                await migration_manager.run_migrations()
                return
            except Exception as e:
                redacted_err = _redact_sensitive(str(e))
                log.error(f"PostgreSQL connection failed: {redacted_err}. Falling back to SQLite...")
                self.is_postgres = False

        # 2. SQLite Backend (Local standalone zero-config storage)
        self.is_postgres = False
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "syncink_radio.db")
        
        def _init_sqlite():
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    welcome_channel_id INTEGER,
                    log_channel_id INTEGER,
                    autorole_id INTEGER,
                    log_channel_moderation INTEGER,
                    automod_log_channel_id INTEGER,
                    music_channel_id INTEGER,
                    dj_role_id INTEGER
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS mod_cases (
                    case_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    mod_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
            return conn

        self._sqlite_conn = await asyncio.to_thread(_init_sqlite)
        log.info(f"Initialized local SQLite database at {db_path}.")

    def _convert_query_to_sqlite(self, query: str) -> str:
        """Converts PostgreSQL $1, $2 parameter placeholders to SQLite ? placeholders."""
        return re.sub(r'\$\d+', '?', query)

    async def fetch(self, query: str, *args) -> List[Any]:
        await self.ensure_connected()
        if self.is_postgres:
            try:
                async with self.pool.acquire() as conn:
                    return await conn.fetch(query, *args)
            except Exception as e:
                redacted_err = _redact_sensitive(str(e))
                log.error(f"DB Fetch Error: {redacted_err}")
                raise DatabaseError(redacted_err)
        else:
            q = self._convert_query_to_sqlite(query)
            def _run():
                cur = self._sqlite_conn.cursor()
                cur.execute(q, args)
                rows = cur.fetchall()
                return [SQLiteRecord(dict(r)) for r in rows]
            return await asyncio.to_thread(_run)

    async def fetchrow(self, query: str, *args) -> Optional[Any]:
        await self.ensure_connected()
        if self.is_postgres:
            try:
                async with self.pool.acquire() as conn:
                    return await conn.fetchrow(query, *args)
            except Exception as e:
                redacted_err = _redact_sensitive(str(e))
                log.error(f"DB FetchRow Error: {redacted_err}")
                raise DatabaseError(redacted_err)
        else:
            q = self._convert_query_to_sqlite(query)
            def _run():
                cur = self._sqlite_conn.cursor()
                cur.execute(q, args)
                row = cur.fetchone()
                return SQLiteRecord(dict(row)) if row else None
            return await asyncio.to_thread(_run)

    async def fetchval(self, query: str, *args) -> Optional[Any]:
        await self.ensure_connected()
        if self.is_postgres:
            try:
                async with self.pool.acquire() as conn:
                    return await conn.fetchval(query, *args)
            except Exception as e:
                redacted_err = _redact_sensitive(str(e))
                log.error(f"DB FetchVal Error: {redacted_err}")
                raise DatabaseError(redacted_err)
        else:
            row = await self.fetchrow(query, *args)
            if row:
                vals = list(row.values())
                return vals[0] if vals else None
            return None

    async def execute(self, query: str, *args) -> str:
        await self.ensure_connected()
        if self.is_postgres:
            try:
                async with self.pool.acquire() as conn:
                    return await conn.execute(query, *args)
            except Exception as e:
                redacted_err = _redact_sensitive(str(e))
                log.error(f"DB Execute Error: {redacted_err}")
                raise DatabaseError(redacted_err)
        else:
            q = self._convert_query_to_sqlite(query)
            def _run():
                cur = self._sqlite_conn.cursor()
                cur.execute(q, args)
                self._sqlite_conn.commit()
                return "SUCCESS"
            return await asyncio.to_thread(_run)

    async def close(self):
        if self.is_postgres and self.pool:
            try:
                await self.pool.close()
            except Exception:
                pass
        if self._sqlite_conn:
            try:
                self._sqlite_conn.close()
            except Exception:
                pass
        log.info("Database connection closed cleanly.")

db = DatabaseManager()
