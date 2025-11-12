from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class AbstractAPIClient(ABC):
    """
    Абстрактный базовый класс (интерфейс) для клиента API блокчейна.
    Определяет методы, которые должен реализовать любой конкретный клиент,
    позволяя легко заменять Etherscan на другой API.
    """

    @abstractmethod
    async def get_latest_block_number(self, chain_id: int) -> int:
        """Получить номер самого последнего блока в сети."""
        pass

    @abstractmethod
    async def get_block_by_number(self, chain_id: int, block_number: int) -> Optional[Dict[str, Any]]:
        """Получить полную информацию о блоке по его номеру."""
        pass
    
    @abstractmethod
    async def get_transaction_receipt(self, chain_id: int, tx_hash: str) -> Optional[Dict[str, Any]]:
        """Получить "квитанцию" транзакции, содержащую адрес контракта."""
        pass

    @abstractmethod
    async def get_contract_source(self, chain_id: int, contract_address: str) -> Optional[Dict[str, Any]]:
        """Получить исходный код и ABI контракта по его адресу."""
        pass

    @abstractmethod
    async def eth_call(self, chain_id: int, to_address: str, data: str) -> Optional[str]:
        """
        Выполняет eth_call для чтения данных из контракта.
        
        :param chain_id: ID сети.
        :param to_address: Адрес контракта.
        :param data: Хеш функции (4 байта) + закодированные аргументы (если есть).
        :return: Результат вызова в виде hex-строки или None при ошибке.
        """
        pass

    @abstractmethod
    async def eth_getCode(self, chain_id: int, address: str) -> Optional[str]:
        """
        Получает код, хранящийся по указанному адресу.
        Возвращает "0x", если код отсутствует (контракт уничтожен).
        """
        pass