# 1. Используйте ПОЛНЫЙ образ, а не -slim
FROM python:3.11

# 2. Установите системные зависимости
#    slither-analyzer требует 'git' и 'build-essential' для компиляции
RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 3. Скопировать и установить зависимости Python
COPY requirements.txt requirements.txt
# (Убедитесь, что slither-analyzer и solc-select есть в requirements.txt)
RUN pip install --no-cache-dir -r requirements.txt

# 4. Устанавливаем Slither и Solc
#    (Этот шаг можно пропустить, если они уже в requirements.txt)
RUN pip install --no-cache-dir slither-analyzer solc-select

# 5. Устанавливаем КОНКРЕТНУЮ ВЕРСИЮ компилятора
RUN solc-select install 0.8.30
RUN solc-select use 0.8.30

ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["python", "-m", "src.main"]