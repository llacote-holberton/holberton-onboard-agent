"""
Planificateur : découvre les tools disponibles via mcp-server (lecture
seule, list_tools() + la resource "config://allowed-tools"), les convertit
au format tool-calling d'Ollama, et les propose au modèle avec le prompt
utilisateur. N'exécute AUCUNE action à effet de bord.

Contrat consommé par backend/app/services/agent_client.py :
  build_plan(prompt) -> (actions, excluded_actions, notice), voir
  build_plan() plus bas pour le détail des trois éléments.

RECONCILIATION (2026-08-20) : fusion de dev_laurent (défaut + résolution
d'alias sur `team`/`name`, visibilité des champs manquants dans le résumé
-- voir _PARAM_ALIASES/_MissingParamAsPlaceholder ci-dessous) et de
Feature/palier3 de Hugo (liste d'outils autorisés via la resource MCP
"config://allowed-tools", tri actions/excluded_actions -- voir
_build_prompt_context ci-dessous). Les deux mécanismes sont orthogonaux et
ne se recouvrent pas.

Extension "boucle d'itération" (palier 4, commit final 0cfdbd0 de Hugo,
après deux DRAFT cbd1235/9b4496b) : construction du plan par relances
successives, plutôt que d'exiger du modèle qu'il énumère toutes les
actions d'un coup en une seule réponse (peu fiable avec un petit modèle
-- confirmé en pratique cette nuit : sur qwen3:0.6b puis même sur
qwen3:8b avec une demande formulée comme "propose un plan complet", le
modèle décrochait complètement du format tool_calls structuré et
répondait en texte libre), on récupère les actions UNE PAR UNE. Après
chaque tool_call d'action, on relance explicitement le modèle avec
_NUDGE ("autre chose ?") avant de finaliser. Chaque proposition n'est PAS
exécutée à ce stade (aucun effet de bord), juste accumulée -- un accusé
de réception factice est renvoyé pour garder la conversation cohérente
(Ollama attend une réponse "tool" par tool_call), jusqu'à ce que le
modèle réponde qu'il n'a plus rien à ajouter.

Un garde-fou (_MAX_TURNS) empêche une boucle infinie si le modèle
n'arrive jamais à une décision finale -- avec une notice explicite plutôt
qu'un plan vide silencieux si ce plafond est atteint sans qu'aucune action
n'ait pu être collectée (voir CORRECTIF dans build_plan).

CORRECTIF (2026-08-20, "mise d'équerre" -- Laurent) appliqué par-dessus le
commit de Hugo : (1) restauration de _build_prompt_context()/
_functional_tools() (supprimées dans son commit, remplacées par du code
inliné) -- mêmes tests qu'avant, mêmes contrats, aucun changement de
comportement, juste pour garder ce module testable sans mcp-server réel ;
(2) suppression du print() de debug laissé par erreur dans le commit de
Hugo ; (3) notice explicite si _MAX_TURNS est atteint sans qu'aucune
action n'ait été collectée.

CORRECTIF #2 (2026-08-20, "let's go") -- list_teams n'est PLUS proposé au
modèle du tout (voir _build_prompt_context) : repro nette et reproductible
cette nuit sur DEUX prompts différents ("Léa" et "Toto"), qwen3:8b y
compris (pas seulement le 0.6b) -- dès qu'un 6e tool (list_teams) était
offert, le modèle décrochait systématiquement du format tool_calls
structuré, MÊME quand il ne l'appelait pas et même sur un prompt trivial,
alors que le même modèle produisait des tool_calls propres avec
seulement 5 tools. Conclusion : la fiabilité du tool-calling de ce modèle
se dégrade avec le nombre d'outils proposés, pas seulement avec la
longueur du prompt -- demander au LLM de vérifier lui-même l'équipe n'est
donc pas fiable, quelle que soit la qualité de l'instruction. La
vérification d'équipe se fait maintenant en CODE (_flag_unknown_teams
ci-dessous), en appelant list_teams nous-mêmes après coup sur les actions
déjà collectées -- même source de vérité, zéro dépendance au
comportement du modèle. Non bloquant par design (pas de retour au
comportement ultra-restrictif) : une équipe non reconnue reste dans
`actions`, juste avec un avertissement visible ajouté au résumé, à
l'humain de trancher. _EXPLORATORY_TOOLS/le code d'exécution exploratoire
dans la boucle restent en place (inertes pour l'instant) au cas où un
futur tool exploratoire s'avère compatible avec un compte de tools plus
faible.

Extension "tools autorisés" : le modèle reçoit TOUS les tools fonctionnels
(autorisés et non autorisés) comme appelables techniquement -- /plan
n'exécute jamais rien à effet de bord, donc aucun risque à le laisser
"choisir" un tool non autorisé. Le tri autorisé/exclu se fait après coup,
de façon déterministe, dans build_plan(), plutôt que de compter sur le
modèle pour décrire correctement en texte ce qu'il n'a pas pu faire.

RECONCILIATION ÉTAPE 2 (2026-08-20, Laurent) : port du mécanisme de
relance CIBLÉE de Feature/palier3 (commit 36add53, Hugo), par-dessus
CORRECTIF #2 ci-dessus. Le _NUDGE générique ("autre chose ?") laissait
trop souvent le modèle s'arrêter avant d'avoir couvert tous les outils
pertinents (repro observée côté Hugo : create_calendar_event
régulièrement omis même quand une réunion était explicitement demandée
dans un plan multi-actions). La relance liste désormais explicitement,
nom + description, les tools fonctionnels pas encore utilisés pour ce
plan -- en excluant toujours les tools exploratoires de cette liste
(cohérent avec CORRECTIF #2 : list_teams n'est de toute façon jamais
proposé au modèle). _NUDGE générique conservé comme repli si tous les
tools fonctionnels ont déjà été utilisés. _MAX_TURNS passe de 6 à 8 pour
la même raison : avec 5 tools fonctionnels, le budget précédent (6)
correspondait exactement au cas nominal (5 tours d'action + 1 tour de
conclusion), sans aucune marge pour une relance supplémentaire ou un
tour "perdu" -- ce qui pouvait à lui seul expliquer l'omission observée
d'un outil pertinent en fin de plan.

RECONCILIATION ÉTAPE 4 (2026-08-20, Laurent) : retrait des deux print()
de debug (tools appelés par tour, texte final à l'arrêt) gardés jusqu'ici
pour la phase de test d'intégration en conditions réelles -- voir revue
critique, section debug prints. Plus nécessaires maintenant que les
étapes 1 à 3 sont validées par les tests unitaires ET testées en
conditions réelles ; à retirer d'un coup plutôt que de les laisser
traîner "temporairement" indéfiniment.
"""

import json
import os
import httpx
from fastmcp import Client
from datetime import date

OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://ollama:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")

MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://mcp-server:8200")
_MCP_ENDPOINT = f"{MCP_SERVER_URL}/mcp"

# RECONCILIATION ÉTAPE 3 (2026-08-20, Laurent), puis 3bis -- coordination
# de la chaîne de timeouts sur les trois couches HTTP (frontend ->
# backend -> agent -> Ollama). Ce timeout-ci est la couche la PLUS À
# L'INTÉRIEUR (un seul appel Ollama) -- point de départ de toute la
# chaîne, chaque couche englobante ajoutant +15s de marge par-dessus
# celle qu'elle enveloppe directement (voir backend/app/config.py::
# AGENT_PLAN_TIMEOUT_SECONDS et frontend/app.py, POST /plans).
#
# ÉTAPE 3bis : lisible via OLLAMA_CALL_TIMEOUT_SECONDS (voir
# .env.example) plutôt qu'en dur -- un seul réglage à changer pour toute
# la chaîne (backend et frontend lisent la MÊME variable d'environnement
# et ajoutent leur propre marge, voir docker-compose.yml) au lieu de
# recalculer 3 nombres à la main à chaque changement de machine ou de
# modèle -- exactement ce qu'on a dû retoucher ce soir en passant de
# qwen3:0.6b à qwen3:8b. Défaut inchangé (110) si la variable est absente
# -- déjà identique entre dev_laurent et Feature/palier3 avant ce soir.
#
# Reste un angle mort assumé (accepté pour l'instant, faute de temps) :
# ce timeout borne UN SEUL appel Ollama, pas la durée totale de
# build_plan(), qui peut en théorie enchaîner jusqu'à _MAX_TURNS appels
# réussis (donc chacun sous ce plafond, mais cumulés). Le pire cas
# théorique (_MAX_TURNS x cette valeur) dépasserait largement la marge
# donnée à la couche backend -- en pratique, un /plan qui enchaînerait
# autant de tours proches du plafond chacun échouerait de toute façon
# bruyamment (ReadTimeout explicite) plutôt que silencieusement, donc
# acceptable comme compromis tant qu'on n'a pas mesuré de latence réelle
# multi-tours.
_OLLAMA_CALL_TIMEOUT = int(os.environ.get("OLLAMA_CALL_TIMEOUT_SECONDS", "110"))

# Garde-fou anti-boucle-infinie : nombre maximum d'allers-retours avec
# Ollama pour un seul /plan (exploration + relances de construction du
# plan confondues). Au-delà, on finalise avec ce qu'on a accumulé (plus
# une notice explicite si rien n'a été collecté -- voir build_plan),
# plutôt que de laisser l'agent tourner indéfiniment.
#
# 8 (au lieu de 6) depuis la RECONCILIATION ÉTAPE 2 -- voir docstring de
# module : avec 5 tools fonctionnels, 6 tours ne laissait aucune marge
# au-delà du cas nominal (5 actions + 1 conclusion).
_MAX_TURNS = 8

# Tools en LECTURE SEULE, sans aucun effet de bord, que le planificateur
# exécute lui-même automatiquement pendant la boucle (contrairement aux
# tools d'action, jamais exécutés ici -- voir executor.py). Distinct de
# la notion d'autorisation (ALLOWED_TOOLS) : ces tools sont toujours
# exécutables pendant la planification, peu importe ALLOWED_TOOLS,
# puisqu'ils ne produisent aucun effet de bord réel.
_EXPLORATORY_TOOLS = {"list_teams"}

# Relance envoyée après chaque action proposée, pour construire le plan
# progressivement plutôt que d'exiger une énumération complète en un seul
# tour (peu fiable en pratique avec un petit modèle -- voir docstring de
# module).
_NUDGE = (
    "As-tu d'autres actions pertinentes à proposer pour compléter cette "
    "demande ? Si oui, appelle le ou les outils correspondants "
    "maintenant. Si non, ou si tu as déjà tout proposé, réponds "
    "uniquement par le mot \"Terminé\", sans appeler aucun outil."
)

_BASE_SYSTEM_PROMPT = (
    "Tu es un agent qui prépare l'arrivée de nouveaux collaborateurs.\n\n"
    "Deux cas selon la formulation de la demande :\n"
    "1. Si l'utilisateur exprime une intention GÉNÉRALE sans lister "
    "d'actions précises (ex: \"prépare l'arrivée de X\"), propose les "
    "actions pertinentes que tu juges nécessaires -- une intention "
    "d'onboarding implique souvent plusieurs actions à la fois. Tu peux "
    "les proposer une par une, on te redemandera s'il en manque.\n"
    "2. Si l'utilisateur LISTE EXPLICITEMENT les actions demandées (verbes "
    "d'action précis comme \"crée X\", \"envoie Y\", \"génère Z\"), "
    "propose un outil correspondant à chaque action listée, sans en "
    "ajouter d'autres non mentionnées.\n\n"
    "Tu ne dois JAMAIS exécuter d'action à effet de bord toi-même : tu "
    "proposes uniquement un plan, qui sera validé par un humain avant "
    "toute exécution.\n\n"
    "Distingue deux types de paramètres :\n"
    "- Paramètres d'IDENTIFICATION (équipe, date, email, identifiant) : "
    "ne les invente jamais au hasard, déduis-les du contexte quand c'est "
    "raisonnable.\n"
    "- Paramètres de CONTENU (checklist, titre, corps de message, canal "
    "de notification) : choisis une valeur par défaut raisonnable plutôt "
    "que de sauter l'outil, l'humain validera de toute façon avant "
    "exécution. Pour le paramètre channel d'un message d'accueil, "
    "utilise 'team' par défaut sauf indication contraire explicite."
)

# Résumés lisibles pour l'écran d'approbation. Légère duplication des noms
# de tools (le set réel reste découvert dynamiquement) -- acceptable tant
# qu'on a un petit nombre de tools fixes, à revoir si le catalogue devient
# très dynamique.
#
# NOTE (2026-08-20) : {team} a été ajouté au template de
# create_employee_record -- condition nécessaire pour que le défaut de
# `team` (voir mcp_server/tools/employee_db.py::_TEAM_PLACEHOLDER) reste
# acceptable : la valeur retenue (fournie par le LLM ou le placeholder de
# repli) doit rester visible ici pour qu'un humain puisse la corriger ou
# refuser l'action, plutôt que d'écrire silencieusement en base une équipe
# potentiellement fausse ou un placeholder non voulu.
_SUMMARY_TEMPLATES = {
    "create_onboarding_issue": "Créer le ticket onboarding pour {employee_name}",
    "create_employee_record": "Créer la fiche employé pour {name} ({role}) — équipe : {team}",
    "send_welcome_message": "Envoyer un message d'accueil ({channel}) à l'équipe {team} pour {employee_name}",
    "generate_handbook": "Générer le document '{template}'",
    "create_calendar_event": "Créer l'événement '{title}'",
}

# Fonctions de compensation ("undo") : outils internes appelés uniquement
# par le backend lors d'une annulation (POST /actions/{id}/undo, voir
# backend/app/services/mcp_client.py), jamais par le LLM au moment du plan
# -- voir docs/TOOLS.md "Outils internes (non exposés au LLM)". mcp-server
# ne fait pourtant aucune distinction structurelle entre un tool de
# création et un tool de compensation (les deux sont juste @mcp.tool dans
# le même fichier -- voir tools/tracker.py, tools/employee_db.py), donc
# list_tools() les renvoie tous pêle-mêle : c'est ici, pas côté
# mcp-server, que le tri se fait avant de les proposer à Ollama.
#
# Orthogonal à la notion d'"autorisation" plus bas (ALLOWED_TOOLS) : une
# fonction interne reste interne même si ALLOWED_TOOLS la mentionnerait
# par erreur -- les deux mécanismes sont vérifiés indépendamment.
_INTERNAL_ONLY_TOOLS = {
    "close_onboarding_issue",
    "delete_employee_record",
}


# Alias de paramètre connus, par tool -- miroir de ce que chaque tool
# déclare côté mcp-server via Field(validation_alias=AliasChoices(...))
# (aujourd'hui : `name`/`employee_name` sur create_employee_record, voir
# mcp_server/tools/employee_db.py). Duplication assumée, même famille que
# _SUMMARY_TEMPLATES et _INTERNAL_ONLY_TOOLS ci-dessus : le schéma JSON que
# list_tools() renvoie n'expose QUE le nom canonique ("name"), jamais
# l'alias, donc _summarize n'a aucun moyen de le découvrir dynamiquement à
# partir du schéma seul. À tenir à jour à la main si un alias est ajouté ou
# retiré côté mcp-server.
_PARAM_ALIASES = {
    "create_employee_record": {"name": ("employee_name",)},
}


def _resolve_known_aliases(tool_name: str, params: dict) -> dict:
    """Complète `params` avec la clé canonique quand seule une clé alias
    connue a été fournie, AVANT de construire le résumé -- voir
    _PARAM_ALIASES ci-dessus. Ne modifie jamais le dict original (c'est
    celui qui est aussi renvoyé tel quel dans l'Action, params bruts
    inclus -- voir build_plan)."""
    aliases = _PARAM_ALIASES.get(tool_name)
    if not aliases:
        return params
    resolved = dict(params)
    for canonical, alt_keys in aliases.items():
        if canonical not in resolved:
            for alt in alt_keys:
                if alt in resolved:
                    resolved[canonical] = resolved[alt]
                    break
    return resolved


class _MissingParamAsPlaceholder(dict):
    """Utilisé par _summarize ci-dessous : quand un champ du template n'a
    pas été fourni par le LLM au moment du plan (ex: `team` omis sur
    create_employee_record), affiche un texte explicite au lieu de faire
    échouer le format() -- le nom du champ manquant est inclus dans le
    texte (pas juste "non fourni" générique), pour rester exploitable
    même quand plusieurs champs manquent sur la même ligne de résumé."""

    def __missing__(self, key):
        return f"({key} non fourni — une valeur par défaut sera utilisée à l'exécution)"


def _summarize(tool_name: str, params: dict) -> str:
    # `params` ici, ce sont les arguments BRUTS renvoyés par le tool-call
    # du LLM, AVANT toute validation/défaut Pydantic côté mcp-server (qui
    # n'a lieu qu'à l'exécution, après approbation humaine). `_resolve_
    # known_aliases` doit passer AVANT le format_map : sinon un champ
    # fourni sous un alias connu (ex: `employee_name` au lieu de `name`)
    # serait affiché comme "non fourni", ce qui serait faux.
    params_for_summary = _resolve_known_aliases(tool_name, params)
    template = _SUMMARY_TEMPLATES.get(tool_name)
    if template:
        try:
            return template.format_map(_MissingParamAsPlaceholder(params_for_summary))
        except (IndexError, ValueError):
            pass
    if params:
        readable = ", ".join(f"{k}: {v}" for k, v in params.items())
        return f"{tool_name} ({readable})"
    return f"Exécuter {tool_name}"


def _functional_tools(tools: list) -> dict:
    """Filtre les fonctions de compensation internes (_INTERNAL_ONLY_TOOLS)
    hors de la liste brute renvoyée par list_tools() -- le LLM ne doit
    jamais pouvoir les choisir dans un plan, autorisé ou pas, ni les
    utiliser comme tool exploratoire. Fonction pure, testable sans
    dépendre d'un vrai mcp-server ni du package fastmcp."""
    return {t.name: t for t in tools if t.name not in _INTERNAL_ONLY_TOOLS}


def _to_ollama_tool(t) -> dict:
    """Convertit un seul objet Tool MCP (déjà en JSON Schema pour ses
    paramètres) au format tool-calling d'Ollama."""
    return {
        "type": "function",
        "function": {
            "name": t.name,
            "description": t.description or "",
            "parameters": t.inputSchema,
        },
    }


async def _discover_tool_permissions() -> tuple[list, dict]:
    """Retourne (tools_mcp_bruts, permissions), permissions étant le
    contenu de la resource "config://allowed-tools" (allowed /
    registered_but_not_allowed / allowed_but_not_registered)."""
    async with Client(_MCP_ENDPOINT) as mcp_client:
        tools = await mcp_client.list_tools()
        resource_result = await mcp_client.read_resource("config://allowed-tools")

    permissions = json.loads(resource_result[0].text)

    return tools, permissions


def _build_system_prompt() -> str:
    return _BASE_SYSTEM_PROMPT + (
        f"\n\nNous sommes le {date.today().isoformat()}. "
        "Quand une date est relative (\"lundi prochain\", \"dans 2 semaines\"), "
        "calcule la date exacte au format YYYY-MM-DD avant d'appeler un outil."
    )


async def _build_prompt_context(prompt: str) -> tuple[list[dict], str, set[str]]:
    """Donne TOUS les tools fonctionnels ET AUTORISABLES (autorisés + non
    autorisés) comme choix possibles au modèle -- /plan n'exécute jamais
    rien à effet de bord, donc aucun risque à le laisser "choisir" un
    tool non autorisé. Le tri autorisé/exclu se fait après coup, de façon
    déterministe, dans build_plan() ci-dessous.

    Les tools EXPLORATOIRES (_EXPLORATORY_TOOLS, ex: list_teams) sont
    exclus de `ollama_tools` -- donc jamais proposés au modèle du tout --
    voir CORRECTIF #2 dans le docstring de module : leur simple présence
    dans la liste cassait la fiabilité du tool-calling structuré, même
    sur qwen3:8b. Ils restent dans `functional_tools`/`allowed_names`
    (bookkeeping), juste jamais envoyés à Ollama."""
    tools, permissions = await _discover_tool_permissions()

    functional_tools = _functional_tools(tools)
    allowed_names = set(permissions["allowed"]) & functional_tools.keys()

    ollama_tools = [
        _to_ollama_tool(t) for t in functional_tools.values()
        if t.name not in _EXPLORATORY_TOOLS
    ]

    system_prompt = _build_system_prompt()

    return ollama_tools, system_prompt, allowed_names


async def _fetch_valid_teams() -> set[str] | None:
    """Appelle list_teams NOUS-MÊMES (pas le LLM) -- voir CORRECTIF #2
    dans le docstring de module. Renvoie None si l'appel échoue pour
    n'importe quelle raison (mcp-server indisponible, tool absent, etc.)
    -- la vérification d'équipe ne doit jamais faire échouer la
    génération du plan, juste l'enrichir quand elle est possible."""
    try:
        async with Client(_MCP_ENDPOINT) as mcp_client:
            result = await mcp_client.call_tool("list_teams", {})
        return set(result.data)
    except Exception:
        return None


async def _flag_unknown_teams(actions: list[dict]) -> None:
    """Modifie `actions` EN PLACE : ajoute un avertissement visible au
    `summary` de toute action dont le paramètre `team` ne correspond à
    aucune équipe réelle -- voir CORRECTIF #2 dans le docstring de
    module. Volontairement NON bloquant : l'action reste dans `actions`,
    l'humain décide à l'approbation (refuser, ou corriger côté
    mcp-server/fixture si l'annuaire est simplement en retard) --
    contrairement à une exclusion pure et dure qui recréerait le
    comportement trop restrictif qu'on cherche justement à éviter."""
    teams_used = {a["params"].get("team") for a in actions if a["params"].get("team")}
    if not teams_used:
        return  # aucune action ne porte de paramètre `team` -- rien à vérifier

    valid_teams = await _fetch_valid_teams()
    if valid_teams is None:
        return  # vérification indisponible -- on n'invente pas un résultat

    for action in actions:
        team = action["params"].get("team")
        if team and team not in valid_teams:
            action["summary"] = (
                f"⚠️ équipe « {team} » non reconnue (équipes valides : "
                f"{', '.join(sorted(valid_teams))}) -- {action['summary']}"
            )


async def build_plan(prompt: str) -> tuple[list[dict], list[dict], str | None]:
    """Retourne (actions, excluded_actions, notice).

    Boucle multi-tours (palier 4) : construction du plan par relances
    successives ("autre chose ?"), plutôt qu'une énumération complète
    exigée en un seul tour -- voir le docstring du module pour le détail.
    (L'exécution de tools exploratoires DANS la boucle, ex: list_teams,
    reste supportée par le code mais n'est plus jamais déclenchée
    actuellement, puisque _build_prompt_context ne propose plus aucun
    _EXPLORATORY_TOOLS au modèle -- voir CORRECTIF #2. La vérification
    d'équipe se fait après coup, en code, via _flag_unknown_teams.)

    - actions : outils autorisés que le modèle a choisi d'appeler,
      accumulés au fil des tours, avec un avertissement ajouté au
      `summary` si `team` ne correspond à aucune équipe réelle connue
      (_flag_unknown_teams, non bloquant).
    - excluded_actions : outils NON autorisés que le modèle aurait
      appelés si rien ne l'en empêchait -- même format que actions, plus
      une note expliquant pourquoi ce n'est pas exécutable actuellement.
    - notice : texte du modèle quand ni l'un ni l'autre n'a été produit
      (ex: demande hors-scope), OU message explicite si _MAX_TURNS est
      atteint sans qu'aucune action n'ait pu être collectée."""
    ollama_tools, system_prompt, allowed_names = await _build_prompt_context(prompt)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    collected_action_calls: list[dict] = []
    final_text: str | None = None
    concluded = False  # True dès que le modèle répond sans tool_calls (fin normale)

    mcp_client_cm = None
    mcp_client = None
    try:
        async with httpx.AsyncClient(timeout=_OLLAMA_CALL_TIMEOUT) as client:
            for turn in range(_MAX_TURNS):
                r = await client.post(
                    f"{OLLAMA_API_BASE}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": messages,
                        "tools": ollama_tools,
                        "think": False,
                        "stream": False,
                        "options": {"temperature": 0.1},
                    },
                )
                r.raise_for_status()
                data = r.json()

                assistant_message = data.get("message", {})
                tool_calls = assistant_message.get("tool_calls", [])

                if not tool_calls:
                    # Réponse finale en texte -- soit rien à proposer du
                    # tout (premier tour), soit "Terminé" après relance.
                    final_text = assistant_message.get("content")
                    concluded = True
                    break

                messages.append(assistant_message)

                exploratory_calls = [
                    c for c in tool_calls if c["function"]["name"] in _EXPLORATORY_TOOLS
                ]
                action_calls = [
                    c for c in tool_calls if c["function"]["name"] not in _EXPLORATORY_TOOLS
                ]

                # Exploration : exécutée réellement (lecture seule, sans
                # risque), résultat renvoyé pour enrichir le contexte.
                # Ouverture paresseuse du client MCP -- seulement ici,
                # pas avant (la plupart des tours n'en ont pas besoin).
                if exploratory_calls and mcp_client is None:
                    mcp_client_cm = Client(_MCP_ENDPOINT)
                    mcp_client = await mcp_client_cm.__aenter__()

                for call in exploratory_calls:
                    fn = call["function"]
                    result = await mcp_client.call_tool(fn["name"], fn.get("arguments", {}))
                    messages.append({
                        "role": "tool",
                        "tool_name": fn["name"],
                        "content": json.dumps(result.data),
                    })

                # Actions : jamais exécutées ici (aucun effet de bord
                # pendant la planification) -- juste accumulées, avec un
                # accusé de réception factice pour garder la conversation
                # cohérente (chaque tool_call attend une réponse "tool").
                for call in action_calls:
                    fn = call["function"]
                    collected_action_calls.append(call)
                    messages.append({
                        "role": "tool",
                        "tool_name": fn["name"],
                        "content": "Proposition enregistrée pour le plan.",
                    })

                if action_calls and not exploratory_calls:
                    # Au moins une action proposée ce tour, rien à
                    # explorer en parallèle : relance CIBLÉE plutôt que
                    # générique -- énumère explicitement les tools pas
                    # encore utilisés, avec leur description. Un petit
                    # modèle répond plus fiablement à une checklist
                    # concrète qu'à un simple rappel ouvert ("autre
                    # chose ?"), qui laissait trop souvent le modèle
                    # s'arrêter avant d'avoir couvert tous les outils
                    # pertinents (repro observée : create_calendar_event
                    # régulièrement omis même quand une réunion était
                    # explicitement demandée dans un plan multi-actions).
                    # Voir RECONCILIATION ÉTAPE 2 dans le docstring de
                    # module.
                    #
                    # On énumère à partir de `ollama_tools` (déjà au
                    # format tool-calling d'Ollama, name+description
                    # inclus) plutôt que de re-dériver `functional_tools`
                    # ici : `ollama_tools` exclut déjà structurellement
                    # les tools exploratoires (CORRECTIF #2), donc aucun
                    # filtre `_EXPLORATORY_TOOLS` supplémentaire n'est
                    # nécessaire, et la signature de _build_prompt_context
                    # (donc les tests qui la mockent) reste inchangée.
                    used_names = {c["function"]["name"] for c in collected_action_calls}
                    remaining = [
                        t["function"] for t in ollama_tools
                        if t["function"]["name"] not in used_names
                    ]
                    if remaining:
                        remaining_list = "\n".join(
                            f"- {t['name']} : {t['description'] or ''}"
                            for t in remaining
                        )
                        nudge = (
                            "Voici les outils que tu n'as pas encore utilisés pour ce "
                            f"plan :\n{remaining_list}\n\n"
                            "Est-ce que l'un d'eux est pertinent pour compléter la "
                            "demande initiale ? Si oui, appelle-le maintenant. Si "
                            "aucun n'est pertinent, réponds uniquement par le mot "
                            "\"Terminé\", sans appeler aucun outil."
                        )
                    else:
                        nudge = _NUDGE
                    messages.append({"role": "user", "content": nudge})
                # Sinon (exploration seule, ou mélange) -> on reboucle
                # directement, le modèle reprend avec le contexte enrichi.
    finally:
        if mcp_client_cm is not None:
            await mcp_client_cm.__aexit__(None, None, None)

    actions = []
    excluded_actions = []
    for call in collected_action_calls:
        fn = call["function"]
        tool_name = fn["name"]
        params = fn.get("arguments", {})
        summary = _summarize(tool_name, params)

        if tool_name in allowed_names:
            actions.append({"tool": tool_name, "params": params, "summary": summary})
        else:
            excluded_actions.append({
                "tool": tool_name,
                "params": params,
                "summary": summary,
                "note": (
                    "Action non autorisée pour le moment -- contactez "
                    "l'administrateur pour l'activer."
                ),
            })

    await _flag_unknown_teams(actions)

    notice = None
    if not actions and not excluded_actions:
        if concluded:
            notice = final_text or None
        else:
            notice = (
                f"Je n'ai pas pu conclure après {_MAX_TURNS} tours -- "
                "reformulez la demande, ou réessayez."
            )

    return actions, excluded_actions, notice
