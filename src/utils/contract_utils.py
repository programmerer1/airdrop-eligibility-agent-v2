# src/utils/contract_utils.py
import logging
import json
from typing import Dict, Any, Optional, Tuple
from eth_utils import function_signature_to_4byte_selector, to_checksum_address
from eth_abi import decode
import codecs # <--- Добавлен импорт codecs

logger = logging.getLogger(__name__)

def get_function_selector(func_abi: Dict[str, Any]) -> Optional[str]:
    """
    Генерирует селектор функции (4 байта) из её ABI.
    Пример ABI: {'name': 'token', 'type': 'function', 'outputs': [{'type': 'address', 'name': ''}], 'inputs': [], 'stateMutability': 'view'}
    """
    try:
        if func_abi.get('type') != 'function':
            logger.warning(f"ABI item is not a function: {func_abi}")
            return None
            
        func_name = func_abi.get('name')
        if not func_name:
            logger.warning(f"Function ABI missing 'name': {func_abi}")
            return None
            
        inputs = func_abi.get('inputs', [])
        # Проверяем, что inputs это список словарей с ключом 'type'
        if not isinstance(inputs, list):
             logger.warning(f"Function ABI has invalid 'inputs' format: {inputs}")
             return None
        
        input_types_list = []
        for inp in inputs:
            if not isinstance(inp, dict) or 'type' not in inp:
                 logger.warning(f"Invalid input item in ABI: {inp}")
                 return None
            input_types_list.append(inp['type'])
            
        input_types = ','.join(input_types_list)
        
        signature = f"{func_name}({input_types})"
        logger.debug(f"Generated function signature: {signature}")
        
        # --- ИСПРАВЛЕНО: Убран .encode() ---
        # function_signature_to_4byte_selector ожидает строку
        selector_bytes = function_signature_to_4byte_selector(signature)
        # --- Конец исправления ---
        
        # Конвертируем байты селектора в hex-строку 0x...
        selector_hex = codecs.encode(selector_bytes, 'hex').decode('ascii')
        
        return f"0x{selector_hex}"
        
    except Exception as e:
        # Логируем ошибку вместе с ABI, вызвавшим ее
        logger.error(f"Failed to generate function selector for ABI {json.dumps(func_abi)}: {e}", exc_info=True)
        return None

def decode_address_from_eth_call(result: str) -> Optional[str]:
    """
    Декодирует адрес из результата eth_call (hex-строка).
    Предполагается, что функция возвращала один address.
    """
    if not result or not result.startswith("0x") or len(result) < 66: # 0x + 64 hex chars
        logger.warning(f"Invalid eth_call result for address decoding: {result}")
        return None
        
    try:
        # Убираем '0x' и конвертируем hex в байты
        result_bytes = bytes.fromhex(result[2:])
        # Декодируем как ('address',)
        decoded_tuple = decode(['address'], result_bytes)
        
        if decoded_tuple and len(decoded_tuple) > 0 and isinstance(decoded_tuple[0], str):
            # Преобразуем в checksum-адрес для единообразия
            return to_checksum_address(decoded_tuple[0])
        else:
             logger.warning(f"Decoding eth_call result did not yield an address: {decoded_tuple}")
             return None
    except ValueError as e: # Ошибка при bytes.fromhex
         logger.error(f"Failed to convert hex result to bytes: {result}. Error: {e}")
         return None
    except Exception as e: # Другие ошибки декодирования
        logger.error(f"Failed to decode address from eth_call result {result}: {e}", exc_info=True)
        return None

# --- НОВЫЙ МЕТОД ---
def decode_timestamp_from_eth_call(result: str) -> Optional[int]:
    """
    Декодирует timestamp (uint256) из результата eth_call.
    Возвращает 0, если результат '0x' или 0.
    Возвращает None, если результат - ошибка.
    """
    if not result or not result.startswith("0x"):
        logger.warning(f"Invalid eth_call result for timestamp decoding: {result}")
        return None
        
    try:
        # Пытаемся конвертировать hex в int
        timestamp = int(result, 16)
        
        if timestamp == 0:
             logger.debug("eth_call returned 0 or '0x'.")
             return 0 # 0 - валидный, но "пустой" результат
             
        # Простая эвристика, чтобы отсеять явный мусор (например, хэши)
        # Если timestamp больше 10,000,000,000 (01/05/2286) - это, вероятно, не дата.
        if timestamp > 10_000_000_000:
             logger.warning(f"Decoded timestamp {timestamp} seems too large to be valid. Treating as invalid.")
             return None # Считаем мусором
             
        return timestamp
        
    except ValueError as e:
        logger.error(f"Failed to decode timestamp from hex result {result}: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error decoding timestamp {result}: {e}", exc_info=True)
        return None

def is_code_empty(code_result: Optional[str]) -> bool:
    """
    Проверяет результат eth_getCode, чтобы определить, пуст ли контракт
    (уничтожен или EOA).
    
    Возвращает True, если:
    - code_result == "0x" (стандартный пустой)
    - code_result == "0x0" или "0x00" и т.д. (любое значение, равное 0)
    
    Возвращает False, если:
    - code_result is None (ошибка API или невалидный ответ)
    - code_result == "0x123..." (есть код)
    """
    if code_result is None:
        # Мы не знаем, пуст ли он, так как API-вызов не удался.
        # Безопаснее считать, что он НЕ пуст, и повторить попытку в след. цикле.
        return False 

    if code_result == "0x":
        # Стандартный ответ для EOA или уничтоженного контракта
        return True

    try:
        # Пытаемся интерпретировать как число. 
        # '0x0', '0x00', '0x000000' все равны 0.
        # '0x123...' будет > 0.
        code_int = int(code_result, 16)
        return code_int == 0
    except ValueError:
        # '0x' был обработан. Если здесь ошибка, это '0x' с не-hex символами
        logger.warning(f"is_code_empty received non-hex value: {code_result}")
        return False # Не можем доказать, что он пуст
    except Exception as e:
        logger.error(f"is_code_empty unexpected error on {code_result}: {e}")
        return False # Безопаснее считать, что он не пуст