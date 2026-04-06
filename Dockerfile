FROM python:3.12-slim

WORKDIR /app

# Install litestream for SQLite WAL replication
ADD https://github.com/benbjohnson/litestream/releases/download/v0.3.13/litestream-v0.3.13-linux-amd64.tar.gz /tmp/litestream.tar.gz
RUN tar -C /usr/local/bin -xzf /tmp/litestream.tar.gz && rm /tmp/litestream.tar.gz

COPY pyproject.toml .
COPY overwatch/ overwatch/

RUN pip install --no-cache-dir .

# Litestream config and data directory
COPY litestream.yml /etc/litestream.yml
RUN mkdir -p /data

# Entrypoint script (litestream restore + replicate, or plain uvicorn)
COPY run.sh /app/run.sh
RUN chmod +x /app/run.sh

ENV OVERWATCH_DATABASE_URL=sqlite:////data/overwatch.db

EXPOSE 8080

CMD ["/app/run.sh"]
