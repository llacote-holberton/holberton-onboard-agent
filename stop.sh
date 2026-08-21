#!/bin/bash

# Parse command-line options
PURGE=false
for arg in "$@"; do
  case $arg in
    --purge)
      PURGE=true
      echo "Purge mode enabled: Docker volumes will be removed."
      ;;
  esac
done

# Stopping all docker services across ALL profiles (including ollama)
if [ "$PURGE" = true ]; then
  echo "Stopping all containers and removing associated volumes..."
  docker compose --profile "*" down -v
else
  echo "Stopping all containers..."
  docker compose --profile "*" down
fi

echo "Docker services stopped successfully!"
