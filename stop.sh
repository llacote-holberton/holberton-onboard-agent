#!/bin/bash

# Parse command-line options
PURGE=false
for arg in "$@"; do
  case $arg in
    --purge)
      PURGE=true
      echo "Purge mode enabled: Docker volumes AND ./data contents will be removed."
      ;;
  esac
done

# Stopping all docker services across ALL profiles (including ollama)
if [ "$PURGE" = true ]; then
  echo "Stopping all containers and removing associated volumes..."
  docker compose --profile "*" down -v

  # DATA_HOST_DIR (bind-mounted business data: onboarding.db, generated
  # PDFs/ics files...) is a host directory, NOT a Docker volume -- "down -v"
  # above never touches it. Wipe its contents too so --purge is a true
  # full reset, reading the same variable used by docker-compose.yml
  # (falls back to ./data, matching .env.example's default) so this stays
  # correct even if you customized it in .env.
  if [ -f .env ]; then
    # shellcheck disable=SC1091
    DATA_HOST_DIR=$(grep -E '^DATA_HOST_DIR=' .env | tail -n1 | cut -d '=' -f2-)
  fi
  DATA_HOST_DIR="${DATA_HOST_DIR:-./data}"

  if [ -d "$DATA_HOST_DIR" ]; then
    echo "Removing contents of '$DATA_HOST_DIR' (database, generated files)..."
    rm -rf -- "${DATA_HOST_DIR:?}"/*
  fi
else
  echo "Stopping all containers..."
  docker compose --profile "*" down
fi

echo "Docker services stopped successfully!"
