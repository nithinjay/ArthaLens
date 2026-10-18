#!/bin/sh
# Create .env from .env.example with random local-development secrets.
# Refuses to overwrite an existing .env (it may hold your Gemini key).
set -eu

cd "$(dirname "$0")/.."

if [ -f .env ]; then
  echo ".env already exists — leaving it unchanged."
  exit 0
fi

rand() { openssl rand -hex 24; }

sed \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand)|" \
  -e "s|^APP_MIGRATE_DB_PASSWORD=.*|APP_MIGRATE_DB_PASSWORD=$(rand)|" \
  -e "s|^APP_API_DB_PASSWORD=.*|APP_API_DB_PASSWORD=$(rand)|" \
  -e "s|^APP_AI_DB_PASSWORD=.*|APP_AI_DB_PASSWORD=$(rand)|" \
  -e "s|^AI_SERVICE_TOKEN=.*|AI_SERVICE_TOKEN=$(openssl rand -hex 32)|" \
  .env.example > .env
chmod 600 .env

echo "Created .env with random local secrets."
echo "Add GEMINI_API_KEY to .env yourself when Milestone 4 needs it."
