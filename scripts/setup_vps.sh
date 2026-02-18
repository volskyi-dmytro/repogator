#!/bin/bash
# One-time VPS setup script for RepoGator
set -euo pipefail

echo "Setting up RepoGator on VPS..."

# Create app directory
sudo mkdir -p /opt/repogator
sudo chown ubuntu:ubuntu /opt/repogator

# Create data directories
sudo mkdir -p /data/chromadb
sudo chown ubuntu:ubuntu /data/chromadb

# Copy .env if not exists
if [ ! -f /opt/repogator/.env ]; then
    echo "WARNING: Copy .env.example to /opt/repogator/.env and fill in values"
fi

echo "Setup complete. Next steps:"
echo "1. Copy docker-compose.prod.yml to /opt/repogator/"
echo "2. Create /opt/repogator/.env with all values from .env.example"
echo "3. Run: docker compose -f docker-compose.prod.yml up -d"
