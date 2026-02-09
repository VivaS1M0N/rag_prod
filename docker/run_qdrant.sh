#!/usr/bin/env bash
set -euo pipefail

# Qdrant persistence directory MUST be outside your code folder to survive deployments.
DATA_DIR="${QDRANT_DATA_DIR:-/opt/qdrant_storage}"

echo "Using Qdrant data dir: $DATA_DIR"
sudo mkdir -p "$DATA_DIR"

# Qdrant docker image usually runs as uid 1000. If you see permission issues, uncomment:
# sudo chown -R 1000:1000 "$DATA_DIR"

docker rm -f qdrant >/dev/null 2>&1 || true

docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v "$DATA_DIR":/qdrant/storage \
  qdrant/qdrant:latest

echo "Qdrant started."
echo "Health: curl -s http://127.0.0.1:6333/collections | head"
