from typing import Optional
import aiomysql
from ..config import MYSQL_HOST, MYSQL_DATABASE, MYSQL_USER, MYSQL_PASSWORD, MYSQL_PORT

class MySQLConnector:
    def __init__(
        self,
        minsize: int = 1,
        maxsize: int = 10,
        autocommit: bool = False,
    ):
        self.host = MYSQL_HOST
        self.db = MYSQL_DATABASE
        self.user = MYSQL_USER
        self.password = MYSQL_PASSWORD
        self.port = int(MYSQL_PORT)

        self.minsize = minsize
        self.maxsize = maxsize
        self.autocommit = autocommit

        self._pool: Optional[aiomysql.Pool] = None

    async def init_pool(self) -> aiomysql.Pool:
        if self._pool is None:
            self._pool = await aiomysql.create_pool(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                db=self.db,
                minsize=self.minsize,
                maxsize=self.maxsize,
                autocommit=self.autocommit,
            )
        return self._pool
    
    async def get_pool(self) -> aiomysql.Pool:
        if self._pool is None:
            raise RuntimeError("The connection pool has not been initialized. Call init_pool() first.")
        return self._pool

    async def close_pool(self):
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            self._pool = None
