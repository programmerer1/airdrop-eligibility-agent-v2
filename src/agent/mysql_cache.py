from datetime import datetime, timedelta
from typing import Optional
import json
from src.db_class.mysql_connector import MySQLConnector

class MySQLCache:
    def __init__(self, connector: MySQLConnector, default_ttl_hours: int = 24):
        self.connector = connector
        self.default_ttl = timedelta(hours=default_ttl_hours)

    async def get(self, cache_key: str, ttl_hours: Optional[int] = None) -> Optional[str]:
        ttl = timedelta(hours=ttl_hours or self.default_ttl.total_seconds() / 3600)
        valid_since = datetime.utcnow() - ttl

        pool = await self.connector.init_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT cache_value
                    FROM research_cache
                    WHERE cache_key = %s
                      AND created_at >= %s
                    LIMIT 1
                    """,
                    (cache_key, valid_since),
                )
                row = await cur.fetchone()
                if row:
                    return json.loads(row[0])
                return {}

    async def set(self, cache_key: str, cache_value: str):
        created_at = datetime.utcnow().replace(microsecond=0)

        pool = await self.connector.init_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO research_cache (cache_key, cache_value, created_at)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        cache_value = %s,
                        created_at = %s
                    """,
                    (cache_key, cache_value, created_at, cache_value, created_at),
                )
            await conn.commit()
