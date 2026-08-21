#!/bin/bash
# LLM CONFIGURATION -- AGNOSTIQUE (2026-08-21, Laurent) -- voir README.md
# "LLM Provider: any provider, any model" et .env.example.
#
# Point d'entrée recommandé pour démarrer la stack : détecte
# automatiquement si LLM_MODEL_NAME (dans .env) désigne un modèle local
# via Ollama et, si c'est le cas, gère les deux étapes supplémentaires
# que ça implique (profil Compose "local-llm" + téléchargement du modèle)
# -- sinon (Anthropic, OpenAI, ou tout autre fournisseur distant), un
# simple `docker compose up -d --build` suffit et rien de plus n'est
# nécessaire. `./stop.sh` reste la commande pour arrêter la stack, quel
# que soit le modèle utilisé (voir README.md "Stopping").
set -euo pipefail

# 1. Lecture et exposition des variables d'environnement custom à Docker.
set -o allexport
source .env
set +o allexport

LLM_MODEL_NAME="${LLM_MODEL_NAME:-anthropic/claude-sonnet-4-6}"

# 2. Modèle local (Ollama) détecté -> active le profil Compose dédié.
#    Les deux préfixes LiteLLM sont reconnus ("ollama_chat/" est le
#    chemin RECOMMANDÉ pour un tool-calling fiable -- route vers l'API
#    /api/chat d'Ollama plutôt que /api/generate ; "ollama/" reste
#    accepté pour compatibilité mais déconseillé -- voir agent/
#    planner.py, section OLLAMA de son docstring de module, et
#    .env.example).
if [[ "$LLM_MODEL_NAME" == ollama/* || "$LLM_MODEL_NAME" == ollama_chat/* ]]; then
  echo "Modèle local détecté (LLM_MODEL_NAME=$LLM_MODEL_NAME) : activation du profil Compose 'local-llm'."
  export COMPOSE_PROFILES=local-llm
else
  echo "Modèle distant détecté (LLM_MODEL_NAME=$LLM_MODEL_NAME) : Ollama ignoré, aucune étape supplémentaire nécessaire."
fi

# 3. Démarrage de tous les services (plus 'ollama' si le profil est actif).
docker compose up -d --build

# 4. Étape supplémentaire propre au cas "modèle local" : attendre qu'Ollama
#    soit prêt, puis télécharger le tag demandé s'il n'est pas déjà présent
#    -- Ollama ne le fait jamais automatiquement, voir README.md.
if [[ "$LLM_MODEL_NAME" == ollama/* || "$LLM_MODEL_NAME" == ollama_chat/* ]]; then
  CONTAINER_NAME="${COMPOSE_PROJECT_NAME:-hbn-onboarder}-ollama"

  echo "Attente de la disponibilité du conteneur Ollama..."
  until docker exec "$CONTAINER_NAME" ollama list > /dev/null 2>&1; do
    sleep 2
  done

  # "ollama_chat/qwen3:8b" -> "qwen3:8b" (ou "ollama/qwen3:8b" -> "qwen3:8b")
  MODEL_TAG="${LLM_MODEL_NAME#ollama_chat/}"
  MODEL_TAG="${MODEL_TAG#ollama/}"

  if docker exec "$CONTAINER_NAME" ollama list | grep -q "$MODEL_TAG"; then
    echo "Modèle '$MODEL_TAG' déjà présent, tout est prêt."
  else
    echo "Téléchargement du modèle '$MODEL_TAG' (première utilisation, peut prendre plusieurs minutes)..."
    docker exec -t "$CONTAINER_NAME" ollama pull "$MODEL_TAG"
    echo "Téléchargement terminé."
  fi
fi

echo "Stack prête. Frontend : http://localhost:${FRONTEND_PORT:-8501}"
