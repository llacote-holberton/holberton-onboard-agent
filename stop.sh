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
    # Les fichiers dans ce dossier sont écrits par les conteneurs
    # (mcp-server, backend), qui tournent en root par défaut (aucun de
    # leurs Dockerfile ne définit de USER) -- ils appartiennent donc à
    # root:root côté host, et un simple "rm -rf" avec l'utilisateur
    # courant échoue avec "Permission non accordée" dès qu'un fichier a
    # déjà été généré par l'app. On délègue donc la suppression à un
    # conteneur jetable (root à l'intérieur, comme les services eux-mêmes),
    # qui peut supprimer ces fichiers quel que soit leur propriétaire --
    # pas besoin de sudo, pas de changement d'architecture des services.
    echo "Removing contents of '$DATA_HOST_DIR' (database, generated files)..."
    ABS_DATA_HOST_DIR="$(cd "$DATA_HOST_DIR" && pwd)"
    docker run --rm -v "${ABS_DATA_HOST_DIR}:/purge" busybox sh -c 'rm -rf -- /purge/*'
  fi
else
  echo "Stopping all containers..."
  docker compose --profile "*" down
fi

echo "Docker services stopped successfully!"
