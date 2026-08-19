"""
Interroge directement l'endpoint /plan de l'agent (sans passer par le
backend ni le frontend) pour voir exactement quelles actions le LLM
propose pour un prompt donne -- utile pour verifier si le nombre d'actions
varie d'un essai a l'autre (instabilite du function-calling avec un petit
modele) ou si c'est systematiquement le meme resultat (bug reproductible).

N'utilise que la bibliotheque standard (urllib) -- pas besoin d'installer
`requests`. Le port de l'agent est publie vers l'hote dans
docker-compose.yml (AGENT_PORT, 8100 par defaut).

Usage :
    python scripts/test_plan_endpoint.py
    python scripts/test_plan_endpoint.py --times 5
    python scripts/test_plan_endpoint.py --prompt "Un autre prompt de test"
"""

import argparse
import json
import os
import urllib.error
import urllib.request

AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:8100")
DEFAULT_PROMPT = (
    "Préviens l'équipe Backend que Camille commence lundi et ouvre un "
    "ticket de suivi pour son onboarding."
)


def call_plan(prompt: str) -> dict:
    payload = json.dumps({"prompt": prompt}).encode("utf-8")
    request = urllib.request.Request(
        f"{AGENT_URL}/plan",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--times", type=int, default=1, help="Nombre d'appels consecutifs (defaut: 1)")
    args = parser.parse_args()

    print(f"Prompt : {args.prompt!r}\n")

    for i in range(1, args.times + 1):
        try:
            result = call_plan(args.prompt)
        except urllib.error.URLError as exc:
            print(f"[essai {i}] ERREUR reseau : {exc}")
            continue
        except json.JSONDecodeError as exc:
            print(f"[essai {i}] Reponse non-JSON (l'agent a probablement renvoye une erreur) : {exc}")
            continue

        actions = result.get("actions", [])
        print(f"[essai {i}] {len(actions)} action(s) proposee(s) :")
        for action in actions:
            print(f"    - {action.get('tool')}: {action.get('params')}")
        print()


if __name__ == "__main__":
    main()
