from typing import Optional
import aiomysql
from .mysql_connector import MySQLConnector

class BaseRepository:
    """
    Базовый класс репозитория.
    Предоставляет общий доступ к пулу соединений MySQLConnector 
    для всех дочерних репозиториев.
    """
    def __init__(self, connector: MySQLConnector):
        """
        Инициализирует репозиторий.
        
        :param connector: Экземпляр MySQLConnector для получения пула соединений.
        """
        self._connector = connector
        self._pool: Optional[aiomysql.Pool] = None

    async def _get_pool(self) -> aiomysql.Pool:
        """Ленивая инициализация пула, если он еще не получен."""
        if self._pool is None:
            self._pool = await self._connector.get_pool()
        return self._pool

    @property
    async def pool(self) -> aiomysql.Pool:
        """Публичное свойство для доступа к пулу соединений."""
        return await self._get_pool()