FROM python:3.11

RUN apt-get update && apt-get install -y \
    git \
    build-essential \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install --no-cache-dir slither-analyzer solc-select

RUN solc-select install 0.8.30
RUN solc-select use 0.8.30

ENV PYTHONPATH=/app/src

EXPOSE 8000

CMD ["python", "-m", "src.main"]