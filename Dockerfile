# syntax=docker/dockerfile:1.4

    FROM python:3.9-slim as builder

    WORKDIR /app
    COPY . .
    
    RUN apt-get update && \
        apt-get install -y --no-install-recommends git && \
        pip install --no-cache-dir astunparse && \
        rm -rf /var/lib/apt/lists/*
    
    FROM python:3.9-slim
    
    WORKDIR /app
    
    COPY --from=builder /usr/local/lib/python3.9/site-packages /usr/local/lib/python3.9/site-packages
    COPY --from=builder /app /app

    RUN apt-get update && \
        apt-get install -y --no-install-recommends git && \
        rm -rf /var/lib/apt/lists/*
    
    VOLUME /output
    
    ENTRYPOINT ["python", "/app/main.py"]
    