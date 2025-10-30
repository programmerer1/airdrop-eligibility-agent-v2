import logging
import json
import asyncio
import tempfile
import os
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

class SlitherAnalyzer:
    """
    Обертка для запуска анализатора Slither на исходном коде контракта.
    """

    def __init__(self):
        logger.info("SlitherAnalyzer initialized.")

    async def _run_slither(self, target_path: str) -> Dict[str, Any]:
        """
        Запускает Slither в подпроцессе во временном каталоге.
        """
        logger.debug(f"Running Slither in directory: {target_path}")
        process = await asyncio.create_subprocess_exec(
            'slither', '.', '--json', '-', cwd=target_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        stderr_str = stderr.decode('utf-8', errors='ignore').strip()

        if stderr_str:
             logger.warning(f"Slither stderr (dir: {target_path}):\n{stderr_str}")

        slither_result: Dict[str, Any] = {} 
        if stdout:
            try:
                slither_result = json.loads(stdout.decode('utf-8', errors='ignore'))
                logger.debug(f"Slither finished parsing stdout. Success: {slither_result.get('success')}. Return code: {process.returncode}")
            except json.JSONDecodeError:
                logger.error(f"Failed to decode Slither JSON output despite receiving stdout. Output: {stdout.decode('utf-8', errors='ignore')[:500]}")
                slither_result = {"success": False, "results": {}}
                slither_result["error"] = "JSONDecodeError" 
        else:
            logger.warning(f"Slither failed with empty stdout. Return code: {process.returncode}.")
            slither_result = {"success": False, "results": {}}
            slither_result["error"] = "Empty stdout" 

        if slither_result.get("error") is None: 
            slither_result["error"] = "" 
        
        if stderr_str:
            if slither_result["error"]: 
                slither_result["error"] += "\n" 
            slither_result["error"] += f"--- stderr ---\n{stderr_str}"

        if "success" not in slither_result:
             slither_result["success"] = False 
        if "results" not in slither_result:
             slither_result["results"] = {}

        return slither_result

    def _prepare_source_files(self, temp_dir: str, source_code_json_str: str) -> str:
        """
        Распаковывает JSON с исходным кодом во временные файлы.
        Ожидает либо {"source": "..."} либо стандартный JSON Input.
        """
        source_data: Any = None
        try:
            source_data = json.loads(source_code_json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse source_code JSON: {e}. Content: {source_code_json_str[:200]}")
            raise ValueError("Invalid source_code JSON structure") from e

        # --- ИЗМЕНЕНИЕ: Безопасная работа с путями ---
        
        # 1. Получаем абсолютный, канонический путь к временной папке
        safe_temp_dir = os.path.realpath(temp_dir)

        if isinstance(source_data, dict) and 'source' in source_data:
            # Для однофайловых контрактов имя файла жестко задано, это безопасно.
            file_path = os.path.join(safe_temp_dir, "Contract.sol")
            logger.debug(f"Writing single file: {file_path}")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(source_data['source'])
            return safe_temp_dir

        elif isinstance(source_data, dict) and 'sources' in source_data:
            logger.debug(f"Writing multiple files to: {safe_temp_dir}")
            sources = source_data['sources']
            if not isinstance(sources, dict):
                 raise ValueError("'sources' key does not contain a dictionary.")
                 
            for relative_path, content_obj in sources.items():
                if not isinstance(content_obj, dict) or 'content' not in content_obj:
                    logger.warning(f"Skipping invalid source entry: {relative_path}")
                    continue
                
                # 2. Формируем полный путь
                full_path = os.path.realpath(os.path.join(safe_temp_dir, relative_path))

                # 3. ПРОВЕРКА БЕЗОПАСНОСТИ:
                # Убеждаемся, что итоговый путь (full_path) 
                # все еще находится ВНУТРИ нашей временной папки (safe_temp_dir)
                if os.path.commonprefix([safe_temp_dir, full_path]) != safe_temp_dir:
                    logger.error(f"SECURITY ALERT: Path Traversal attempt detected. Blocked path: {relative_path}")
                    # Прерываем всю операцию
                    raise PermissionError(f"Path Traversal attempt detected: {relative_path}")

                logger.debug(f"Writing file: {full_path}")
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(content_obj['content'])
            return safe_temp_dir
        # --- Конец изменений ---

        else:
            logger.error(f"Unknown source_code JSON structure: Expected 'source' or 'sources' key. Got: {str(source_data)[:200]}")
            raise ValueError("Unknown source_code JSON structure: Expected 'source' or 'sources' key.")


    async def analyze_source_code(self, source_code_json: str) -> Dict[str, Any]:
        """
        Анализирует исходный код с помощью Slither.
        """
        # Используем NamedTemporaryFile для более безопасного создания временных каталогов
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                root_path_for_slither = self._prepare_source_files(temp_dir, source_code_json)
                logger.info(f"Prepared source files for Slither in: {root_path_for_slither}")
            except (ValueError, PermissionError) as e: # Ловим наши ошибки валидации
                logger.error(f"Failed to prepare source files: {e}")
                return {"success": False, "error": f"Failed to prepare source files: {e}", "results": {}}
            except Exception as e: # Ловим все остальные ошибки (напр. I/O)
                logger.error(f"Unexpected error preparing source files: {e}", exc_info=True)
                return {"success": False, "error": f"Unexpected error preparing files: {e}", "results": {}}
            
            # Запускаем Slither
            try:
                 slither_result = await self._run_slither(root_path_for_slither)
                 return slither_result
            except Exception as e:
                 logger.error(f"Error running Slither process: {e}", exc_info=True)
                 return {"success": False, "error": f"Error running Slither process: {e}", "results": {}}

    def classify_slither_report(self, slither_json: Dict[str, Any]) -> Tuple[int, str]:
        """
        Классифицирует JSON-отчет Slither по 5-уровневой шкале.
        """
        slither_json_with_provider = slither_json.copy() 
        slither_json_with_provider["provider"] = "Slither"
        report_str = json.dumps({"slither": slither_json_with_provider})
        
        if not slither_json.get('success', False):
            return (1, report_str) 

        detectors = slither_json.get('results', {}).get('detectors')
        if not detectors:
            return (5, report_str) 

        impacts = set(d.get('impact') for d in detectors)
        
        if 'High' in impacts:
            return (3, report_str)
        if 'Medium' in impacts:
            return (2, report_str)
        if 'Low' in impacts:
            return (4, report_str)
            
        return (5, report_str)