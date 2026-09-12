FROM python:3.12-slim

# Set working directory and environment variables
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies (curl, sqlite3, ca-certificates, litestream)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Litestream for SQLite WAL replication (optional disaster recovery)
ADD https://github.com/benbjohnson/litestream/releases/download/v0.3.13/litestream-v0.3.13-linux-amd64.tar.gz /tmp/litestream.tar.gz
RUN tar -C /usr/local/bin -xzf /tmp/litestream.tar.gz && rm /tmp/litestream.tar.gz

# Copy requirements and install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Create persistent storage mount directory
RUN mkdir -p /app/data

# Copy application files and entrypoint script
COPY wanda2-v2.py /app/
COPY entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

# Expose server port
EXPOSE 8000

# Run entrypoint process
ENTRYPOINT ["/app/entrypoint.sh"]
