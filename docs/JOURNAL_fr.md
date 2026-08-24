# JOURNAL.md — Journal de bord du développement (branche `feature/palier5`)

Journal chronologique des décisions prises pendant les paliers 3 à 5, reconstitué à partir de l'historique Git de cette branche (22 commits, Hugo, 20-21/08/2026) et de `eval/cases.md`. Objectif : garder la trace du *pourquoi*, pas seulement du *quoi* — le code et les docstrings disent déjà ce qui a été fait.

## 20/08, matin — Donner une frontière opérateur au catalogue de tools

Jusqu'ici, tout tool enregistré côté `mcp-server` était automatiquement proposable par l'agent. Premier chantier de la journée : introduire `ALLOWED_TOOLS`, une liste blanche configurée côté opérateur (variable d'environnement), indépendante de ce que le modèle est *techniquement capable* de proposer.

Décision de conception importante prise à ce stade : une action non autorisée ne doit **pas disparaître silencieusement** du plan. Elle doit rester visible, barrée, avec une explication — pour que l'utilisateur voie toujours l'intention complète de l'agent, y compris la partie qu'il n'a pas le droit d'exécuter. C'est l'origine du champ `excluded_actions`, distinct de `actions`, qui traverse tout le reste du projet (modèle `Plan`, réponse d'API, affichage Streamlit).

Concrètement, ce matin-là : la resource MCP `config://allowed-tools` (`mcp_server/resources.py`), l'endpoint `/agent/tools` côté backend, l'affichage des actions exclues côté frontend, et le premier filtrage des actions autorisées dans la logique de plan.

## 20/08, midi — Un plan qu'on peut retrouver

Petit chantier isolé mais pratique : persister l'id du plan courant dans l'URL (`st.query_params`) plutôt que dans le seul `session_state` Streamlit, qui est vidé à chaque vrai rechargement de page. Sans ça, un rafraîchissement de page ou un lien partagé perdait le plan en cours.

## 20/08, après-midi — Les premiers brouillons de la boucle multi-tours

Deux commits marqués `DRAFT` : `list_teams` (outil de lecture seule listant les équipes valides de l'annuaire) et une première version de l'exécution exploratoire multi-tours dans `build_plan`. C'est le point de départ du changement le plus structurant du palier 4 : jusque-là, l'agent devait tout décider en un seul appel au modèle. L'idée testée ici — laisser le modèle consulter des informations en cours de route, sur plusieurs tours de conversation avec lui-même — deviendra le cœur de `planner.py`.

## 20/08, fin d'après-midi — La boucle multi-tours passe en production

Le brouillon de l'après-midi est retravaillé et devient la version stable : `build_plan` mène désormais une conversation de plusieurs tours avec le modèle (garde-fou `_MAX_TURNS`), distingue les tools exploratoires (exécutés immédiatement, sans effet de bord) des propositions d'action (jamais exécutées à ce stade, seulement accumulées), et relance systématiquement le modèle après chaque proposition pour lui demander s'il a autre chose à ajouter.

Le prompt système est réécrit en même temps pour refléter ce nouveau mode de fonctionnement — distinguer une intention générale (« propose ce qui te semble pertinent ») d'une liste explicite d'actions (« ne propose que ce qui est demandé »), et rappeler que `list_teams` existe pour vérifier une équipe avant d'agir plutôt que de deviner.

Suivent, la même soirée : l'augmentation du nombre maximum de tours et le passage d'une relance générique (« autre chose ? ») à une relance **ciblée**, qui énumère nommément les outils pas encore utilisés — correctif direct à un problème observé en pratique (voir `eval/cases.md`, cas 2 : `create_calendar_event` était régulièrement oublié par le modèle sur un plan multi-actions, malgré une réunion explicitement demandée ; la relance ciblée corrige ça). L'augmentation du timeout de génération de plan accompagne ce changement — plus de tours veut dire plus d'appels au modèle, donc plus de temps.

Le tool `generate_handbook` (génération de document d'accueil) est également implémenté ce soir-là, avec un renforcement de la validation sur `create_employee_record`.

## 21/08, matin — Rendre les échecs compréhensibles par un humain

Premier chantier du lendemain : quand le modèle produit un appel d'outil mal formé (JSON brut au lieu d'un vrai appel structuré — observé notamment en essayant de provoquer ce cas via une tentative de manipulation du prompt, voir `eval/cases.md` cas 6), ce fragment technique ne doit jamais atterrir tel quel devant l'utilisateur. Un message générique et compréhensible le remplace désormais.

C'est le fil conducteur du palier 5, qui se poursuit toute la journée : **l'utilisateur doit comprendre quoi faire**, jamais lire un message d'erreur pensé pour un développeur.

## 21/08, après-midi — Observabilité, fiabilité, et clôture des tests

Une série de correctifs resserrés en fin d'après-midi :

- **Trace tour par tour** exposée jusque dans l'interface (`plan.trace`, panneau « 🔍 Pourquoi ce plan ? ») — jusqu'ici, la séquence de décisions de l'agent n'était visible que dans les logs Docker. Les timeouts backend/frontend sont retouchés au même moment : avec la boucle à 8 tours désormais possible, le timeout resté à 120s côté backend était devenu insuffisant pour un plan complet (régression concrète documentée dans `eval/cases.md`, cas 2 — corrigée en alignant le timeout backend à 240s et le frontend à 260s).
- **Nettoyage du préfixe technique FastMCP** (`Error calling tool '...':`) sur les messages d'erreur remontés à l'utilisateur (`executor.py::_humanize_error`) — même logique que le matin, appliquée cette fois aux erreurs d'exécution plutôt qu'aux appels mal formés.
- **Warmup du modèle au démarrage** de l'agent, et enrichissement de la structure de réponse du plan.
- **Message d'erreur plus clair** pour un département/équipe inconnu, et ajout d'`eval/cases.md` — le fichier qui documente, cas par cas, ce qui a été testé et son dernier résultat connu.
- **Portage de tests compatibles depuis `dev_laurent`** — une branche parallèle du projet, dont certains tests (sur des tools dont la logique cœur est restée identique) ont pu être récupérés tels quels plutôt que réécrits.
- Dernier commit de la branche à ce jour : encore un tour de vis sur la clarté des messages d'erreur, cette fois sur les endpoints `/plans` et `/execute` eux-mêmes.

## État à date (21/08)

`eval/cases.md` recense 7 scénarios de bout en bout ; 6 passent, le 7ᵉ (garde-fou d'exécution sans exploration préalable) est validé partiellement — il reste à réautoriser temporairement `send_welcome_message` pour confirmer l'échec propre à l'exécution avec une équipe absurde, pas seulement l'absence d'exploration. Voir `AGENTS.md` pour une explication du comportement actuel de l'agent côté utilisateur, et `eval/cases.md` pour le détail cas par cas.

## Comment tenir ce journal à jour

Une entrée par session de travail significative, pas par commit : le *pourquoi* d'un changement de comportement (nouveau garde-fou, régression corrigée, décision de conception assumée), pas la liste mécanique des fichiers touchés — ça, `git log` le fait déjà très bien.
