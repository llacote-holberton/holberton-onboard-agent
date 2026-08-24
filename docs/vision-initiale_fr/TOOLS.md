# Outils de l'agent

Deux catégories : les **tools exposés au LLM** (ceux que l'agent peut choisir d'inclure dans un plan), et les **outils internes** (utilisés par le backend pour orchestrer, mais jamais proposés au LLM comme actions du plan).

Les types `IssueRef`, `EmployeeRef`, `MessageRef`, `DocumentRef`, `EventRef` sont de simples alias de `str` (`domain_types.py`), pas des objets structurés — c'est le choix d'implémentation retenu, plus simple que la version dataclass/Pydantic envisagée initialement.

Ce choix déplace une responsabilité importante sur chaque tool : comme le serveur MCP ne garde aucun état entre deux appels, c'est le backend qui doit porter, d'un appel à l'autre, l'information nécessaire à l'annulation (il stocke déjà le retour du tool dans `Action.result`, et le repasse tel quel au moment du undo — voir `mcp_client.py`). Chaque tool doit donc renvoyer **exactement** la chaîne dont sa fonction de compensation aura besoin, pas un résumé ou un message de confirmation :

| Tool | Ce que la `str` renvoyée doit contenir |
|---|---|
| `create_onboarding_issue` | ~~le numéro/ID de l'issue créée (ex. `"42"`)~~ **correction (2026-08-20) : l'implémentation réelle (`mcp_server/tools/tracker.py`) renvoie `data["html_url"]`, l'URL complète de l'issue (ex. `"https://github.com/owner/repo/issues/42"`), pas juste le numéro.** `close_onboarding_issue` (voir plus bas) en extrait le numéro à partir de cette URL. |
| `create_employee_record` | l'ID de la ligne insérée en base |
| `send_welcome_message` | le `Message-ID` SMTP de l'e-mail envoyé (implémenté ainsi dans `mailbox.py`) — sert surtout de trace pour l'audit, puisque l'annulation reste de toute façon partielle (voir plus bas) |
| `generate_handbook` | le chemin du fichier PDF généré sur le volume |
| `create_calendar_event` | le chemin du fichier `.ics` généré sur le volume |

## Tools exposés au LLM (function-calling)

| # | Nom | Signature typée | Effet de bord |
|---|---|---|---|
| 1 | `create_onboarding_issue` | `create_onboarding_issue(employee_name: str, start_date: date, checklist: list[str]) -> IssueRef` | **Oui** — crée une issue sur GitHub Issues (API réelle) |
| 2 | `create_employee_record` | `create_employee_record(name: str, role: str, start_date: date, team: str = "À préciser") -> EmployeeRef` | **Oui** — insère une ligne en base SQLite |
| 3 | `send_welcome_message` | `send_welcome_message(employee_name: str, team: str, channel: Literal["team", "manager", "it"]) -> MessageRef` | **Oui** — envoie un e-mail SMTP réel vers MailHog |
| 4 | `generate_handbook` | `generate_handbook(employee_id: str, template: Literal["welcome_pack", "mission_letter"]) -> DocumentRef` | **Oui** — génère un fichier PDF sur le volume (Jinja2 + WeasyPrint) |
| 5 | `create_calendar_event` | `create_calendar_event(title: str, event_date: date, duration_minutes: int, attendees: list[str]) -> EventRef` | **Oui** — génère un fichier `.ics` sur le volume |

Chaque tool ci-dessus a une fonction de compensation associée (voir plus bas), appelée lors d'une annulation.

### Fiabilité du function-calling avec un petit modèle local

Repro réelle (2026-08-20, prompt large avec 3 actions demandées) : le LLM a appelé `create_employee_record` avec `employee_name` au lieu de `name`, et a complètement omis `team` -- alors que le prompt mentionnait explicitement l'équipe. Deux remédiations différentes selon le type d'erreur :

- **Confusion de nom de paramètre** (`employee_name` vs `name`) : patchée avec un `Field(validation_alias=AliasChoices("name", "employee_name"))` sur `create_employee_record` -- `name` accepte maintenant les deux clés en entrée, sans changer ce que le schéma JSON expose au LLM (toujours juste `"name"`). Voir `mcp_server/tools/employee_db.py`.
- **Paramètre requis complètement omis** (`team`) : ~~PAS de valeur par défaut (ex. `"all"` a été envisagé et écarté)~~ **décision revue le 2026-08-20 (plus tard la même session), voir "Retour en arrière sur `team`" ci-dessous.**

Un alias absorbe une confusion de *forme* (le LLM avait l'info, mauvaise clé) ; il ne peut rien pour une omission de *contenu* (le LLM n'a pas repris une info qu'il avait). D'où les deux traitements différents à l'origine -- nuancé pour `team` par la mise à jour ci-dessous.

**Mise à jour (2026-08-20, second run réel)** : `send_welcome_message` a cette fois omis `channel` entièrement. Traitement différent de celui de `team` sur `create_employee_record`, et volontairement pas une contradiction : `channel` a reçu une valeur par défaut (`"team"`), alors que `team` sur `create_employee_record` reste sans défaut. Deux raisons à cette distinction :

1. `team` (employee_db) est un **fait** sur la personne (son équipe réelle) -- une valeur inventée écrirait un mensonge en base. `channel` (mailbox) est un **choix de routage** -- "team" est l'interprétation la plus large et la plus sûre d'une demande de bienvenue générique, pas une donnée fabriquée.
2. `team` n'apparaît pas dans le résumé d'approbation de `create_employee_record` (`_SUMMARY_TEMPLATES` ne montre que `{name}`/`{role}`) -- une valeur par défaut y serait invisible pour l'humain avant exécution. `channel`, lui, apparaît dans le résumé de `send_welcome_message` (`{channel}` fait partie du template) -- l'humain voit encore le choix fait et peut refuser l'action.

Voir `mcp_server/tools/mailbox.py::send_welcome_message` pour le détail.

### Retour en arrière sur `team` (2026-08-20, plus tard la même session)

Une deuxième repro réelle consécutive (même run de test que celui qui avait confirmé le fix de l'alias `name`/`employee_name`) a de nouveau vu `team` omis par le LLM. Décision explicite de Laurent : accepter un défaut pour `team` plutôt que de continuer à bloquer l'action, afin d'aller vite et de passer le palier en cours -- quitte à revenir dessus plus tard si besoin.

Ce n'est pas un simple retour au `"all"` écarté au premier tour ; deux différences assumées le rendent acceptable au regard du principe "jamais de fait inventé en silence" :

1. **Le placeholder ne ressemble à aucun nom d'équipe réel.** `_TEAM_PLACEHOLDER = "À préciser"` (`mcp_server/tools/employee_db.py`) saute aux yeux comme une valeur de repli, pas comme une équipe plausible passée inaperçue -- contrairement à `"all"`, qui aurait pu être lu comme une vraie réponse.
2. **La valeur retenue est maintenant visible dans le résumé d'approbation.** `agent/planner.py::_SUMMARY_TEMPLATES["create_employee_record"]` inclut désormais `{team}`. Et comme `_summarize` construit ce résumé à partir des arguments bruts du tool-call du LLM (avant tout défaut Pydantic, qui n'intervient qu'à l'exécution côté mcp-server, après approbation humaine), une omission pure et simple aurait pu rester invisible dans ce résumé -- `_summarize` a donc été corrigé en parallèle (`_MissingParamAsPlaceholder`) pour afficher explicitement "(non fourni — une valeur par défaut sera utilisée à l'exécution)" plutôt que de laisser le champ disparaître silencieusement du résumé. Voir `agent/tests/test_planner.py` pour les deux tests qui verrouillent ce comportement.

Limite assumée : si l'humain approuve sans lire attentivement le résumé, la fiche est bien écrite en base avec `"À préciser"` comme équipe -- pas un problème nouveau (même risque déjà accepté pour `channel` sur `send_welcome_message`), mais à garder à l'oeil si `team` continue d'être fréquemment omis en pratique. La feature "modifier les paramètres d'une action avant validation" (frontend, pas encore commencée) resterait le fix le plus durable si ce palliatif s'avère insuffisant.

## Annuaire factice (`employees_directory.json`)

`send_welcome_message` ne prend pas de `recipient` en texte libre : si on laissait le LLM produire une adresse e-mail, il en inventerait une (violerait "l'agent doit dire qu'il n'a pas pu, plutôt que d'inventer"). À la place, `team` désigne un département, résolu côté MCP server via un annuaire statique versionné avec le code — **pas** la table `employees` de la base SQLite du backend, qui elle ne contient que la personne en cours d'onboarding, pas le personnel existant.

Sémantique de `channel` par rapport à `team` :

| `channel` | Destinataires résolus | `team` utilisé ? |
|---|---|---|
| `"team"` | tous les membres du département `team` | oui |
| `"manager"` | le `manager_email` du département `team` | oui |
| `"it"` | l'équipe IT fixe de l'annuaire (support matériel/comptes, indépendant du département d'arrivée) | non — ignoré |

Si `team` n'existe pas dans l'annuaire, l'outil renvoie une erreur explicite plutôt qu'une adresse inventée ou un envoi silencieusement ignoré (voir `SEQUENCES.md` diagramme 5).

Structure du fichier (4 départements factices : Backend, Frontend, Product, IT), chacun avec un `manager_email` et une liste `members` (nom, e-mail, rôle) — emplacement suggéré `mcp_server/tools/fixtures/employees_directory.json`, à ajuster selon l'arborescence réelle du service.

## Outils internes (non exposés au LLM)

| Nom | Signature typée | Effet de bord |
|---|---|---|
| `check_idempotency` | `check_idempotency(action_key: str) -> bool` | **Non** — lecture seule, vérifie si `action_key` existe déjà dans `AuditLog`/`Action` |
| `log_audit_event` | `log_audit_event(action_id: str, status: Literal["proposed", "approved", "refused", "executed", "undone"]) -> None` | **Oui** — écrit une entrée horodatée dans le journal d'audit |
| `execute_action` | `execute_action(action_id: str) -> ExecutionResult` | **Oui** (indirect) — dispatche vers le bon tool si non déjà exécuté (vérifie `check_idempotency` avant) |
| `undo_last_action` | `undo_last_action(action_id: str) -> bool` | **Oui** — appelle la fonction de compensation du dernier tool exécuté pour cette action |

## Fonctions de compensation (`undo`), une par tool

Design confirmé (2026-08-20) : pas de tool `undo` générique — une fonction de compensation dédiée par tool, typée sur son propre `*Ref`, exactement comme documenté ci-dessous. Voir `backend/app/services/mcp_client.py::_UNDO_SPEC_BY_ACTION_TOOL` pour le dispatch côté backend, qui appelle chacune par son nom. Ces fonctions sont des **outils internes** : `agent/planner.py::_INTERNAL_ONLY_TOOLS` les exclut explicitement de ce qui est proposé au LLM au moment du plan.

`close_onboarding_issue` et `delete_employee_record` sont implémentées ce soir. `mark_message_undone`, `remove_handbook`, `remove_calendar_event` restent à faire (et dépendent respectivement de `send_welcome_message`, `generate_handbook`, `create_calendar_event`, dont seul le premier est aujourd'hui implémenté).

| Tool exécuté | Fonction de compensation | Signature | Effet de bord |
|---|---|---|---|
| `create_onboarding_issue` | `close_onboarding_issue` ✅ | `close_onboarding_issue(issue: IssueRef) -> bool` | **Oui** — ferme l'issue sur GitHub (ne la supprime pas, l'API GitHub ne permet pas la suppression d'issue) |
| `create_employee_record` | `delete_employee_record` ✅ | `delete_employee_record(employee: EmployeeRef) -> bool` | **Oui** — supprime la ligne en base |
| `send_welcome_message` | `mark_message_undone` | `mark_message_undone(message: MessageRef) -> bool` | **Oui, partiel** — marque le message comme "annulé" dans l'audit ; ne peut pas rappeler un e-mail déjà envoyé à MailHog (limite documentée, cf. `SPEC.md`) |
| `generate_handbook` | `remove_handbook` | `remove_handbook(document: DocumentRef) -> bool` | **Oui** — supprime le fichier PDF du volume |
| `create_calendar_event` | `remove_calendar_event` | `remove_calendar_event(event: EventRef) -> bool` | **Oui** — supprime le fichier `.ics` du volume |

> **Note** : `send_welcome_message` est volontairement écarté du scénario de démonstration d'annulation (`HAPPY_PATH.md`) car son "undo" ne peut être que partiel — c'est documenté ici plutôt que dissimulé.
