import logging
import json
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class AirdropABIFilter:
    """
    Выполняет быструю предварительную проверку ABI контракта на наличие
    ключевых слов, указывающих на Airdrop.
    """
    def __init__(self, keywords: List[str]):
        """
        Инициализирует фильтр.
        
        :param keywords: Список ключевых слов (в нижнем регистре) для поиска.
        """
        self._keywords = set(keywords)
        logger.info(f"AirdropABIFilter initialized with keywords: {keywords}")

    def check_abi(self, abi_str: str) -> bool:
        """
        Проверяет ABI на наличие ключевых слов.
        
        :param abi_str: ABI контракта в виде JSON-строки.
        :return: True, если найдено хотя бы одно совпадение, иначе False.
        """
        if not abi_str:
            return False
            
        try:
            abi_data = json.loads(abi_str)
            if not isinstance(abi_data, list):
                logger.warning(f"Invalid ABI format: not a list. ABI: {abi_str[:200]}")
                return False

            # Проверяем все элементы ABI (функции, события и т.д.)
            for item in abi_data:
                if isinstance(item, dict) and 'name' in item:
                    item_name = item['name'].lower()
                    # Проверяем, содержит ли имя функции/события ключевое слово
                    if any(keyword in item_name for keyword in self._keywords):
                        logger.info(f"ABI Filter HIT: Found keyword in '{item_name}'.")
                        return True
                        
            return False
            
        except json.JSONDecodeError:
            logger.warning(f"Failed to decode ABI JSON: {abi_str[:200]}")
            return False
        except Exception as e:
            logger.error(f"Error checking ABI: {e}", exc_info=True)
            return False