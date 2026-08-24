# Diagrammes de séquence

Notation : chaque ligne est un message `Émetteur → Destinataire : contenu`, dans l'ordre chronologique. Les blocs `[alt ...]` / `[loop ...]` indiquent une branche conditionnelle ou une boucle, avec le contenu indenté.

Participants communs (chacun = un container Docker séparé, sauf M) :

- **M** = Manager (utilisateur)
- **F** = Frontend (Streamlit)
- **B** = Backend API (FastAPI) — inclut la vérification d'idempotence et l'écriture de l'audit
- **A** = Agent AI — planifie (construit le prompt, appelle le LLM) et exécute les créations approuvées (dispatch mécanique vers P, jamais de sa propre initiative)
- **L** = Ollama — LLM local (modèle Qwen3)
- **P** = MCP Server — expose et exécute les 5 tools + leurs `undo()`
- **S** = Service externe / volume atteint par un tool (GitHub, MailHog, fichiers)
- **D** = Base de données (SQLite, fichier partagé entre B et P)

---

## 1. Envoi du prompt

```
M → F : saisit "On accueille Camille, nouvelle développeuse, elle arrive
         le 3 mars dans l'équipe Backend."
M → F : clique sur "Générer le plan"
F → F : valide le champ (non vide, longueur raisonnable)
F → F : affiche un indicateur de chargement, désactive le bouton
F → B : POST /plans  { prompt: "..." }
```

Ce diagramme s'arrête à l'émission de la requête HTTP : la suite (traitement côté backend) fait l'objet du diagramme 2.

---

## 2. Génération des tâches

```
B → A : POST /generate  { prompt }

A → P : list_tools()  [MCP, appel de lecture seule]
P → A : schéma des 5 tools (nom, description, paramètres typés)

A → A : construit le prompt système + injecte le schéma reçu
A → L : appel Ollama en mode tool-calling / JSON strict (modèle Qwen3)
L → A : renvoie un JSON structuré { actions: [ {tool, params}, ... ] }

  [alt Ollama indisponible, trop lent, ou réponse invalide]
    A → A : bascule sur le fallback par règles/mots-clés
             (couvre 2-3 intentions types documentées)
  [fin alt]

A → A : valide/normalise le JSON (types, champs requis, dates)
A → B : renvoie la liste des actions proposées

B → D : persiste Plan (status="en_cours") + une ligne Action par tâche
         (status="proposée", idempotency_key = hash(plan_id, tool, params))
B → F : 200 OK  { plan_id, actions: [ {id, tool, résumé, statut}, ... ] }
F → F : affiche les 5 actions sous forme de cases à cocher,
         toutes cochées par défaut
F → M : affiche le plan à valider
```

Remarque : à ce stade, Agent AI n'a fait qu'un appel de lecture (`list_tools`) — il n'appelle `call_tool` que dans le diagramme 3, et uniquement sur les actions que le backend lui aura explicitement désignées comme approuvées par l'humain.

---

## 3. Exécution des tâches

```
M → F : décoche l'action "envoyer le message d'accueil"
M → F : clique sur "Exécuter les actions sélectionnées"

F → B : PATCH /actions/{id}  { decision: "approved" }   (répété par action)
F → B : PATCH /actions/{id}  { decision: "refused" }    (pour l'action décochée)
B → D : met à jour le statut de chaque action + log_audit_event(...)

F → B : POST /plans/{plan_id}/execute

  [loop pour chaque action au statut "approved"]
    B → D : check_idempotency(action.idempotency_key)
    [alt clé déjà présente en base]
      B → D : log_audit_event(action_id, status="executed",
                                note="déjà exécutée, non rejouée")
                                → cette action est exclue de l'envoi à l'agent
    [fin alt]
  [fin loop]

B → A : POST /execute  { action_ids: [ ...actions approuvées ET non déjà exécutées... ] }
         (dispatch mécanique : aucun nouvel appel LLM à ce stade,
          l'agent ne reçoit que ce que le backend a déjà validé)

  [loop pour chaque action_id reçu]
    A → P : call_tool(tool_name, params)  [MCP, appel d'exécution]
             ex. create_onboarding_issue(employee_name, start_date, checklist)
    P → S : effet de bord réel (création issue GitHub /
             envoi SMTP vers MailHog / écriture fichier PDF ou .ics /
             insertion SQLAlchemy dans le SQLite partagé)
    S → P : confirmation (ex. IssueRef{number, url})
    P → A : résultat de l'exécution
  [fin loop]

A → B : résultats agrégés (succès/échec par action)
B → D : pour chaque résultat, enregistre idempotency_key
         + log_audit_event(status="executed")
B → F : 200 OK  { results: [ {action_id, status}, ... ] }
F → F : coche ✅ les actions exécutées, met à jour le journal affiché
F → M : affiche le résultat final (4 exécutées, 1 refusée)
```

Le filtrage par idempotence reste entièrement du ressort du backend, *avant* l'envoi à l'agent : une action déjà exécutée n'est jamais transmise à Agent AI, qui ne peut donc pas la rejouer même s'il le voulait.

---

## 4. Annulation d'une tâche

```
M → F : clique sur "Annuler" en face de "génération du livret d'accueil"
F → B : POST /actions/{action_id}/undo

B → D : charge l'action, vérifie status == "executed"

  [alt action non annulable — déjà "undone" ou compensation impossible]
    B → F : 409 Conflict  { reason: "action déjà annulée" | "non annulable" }
    F → M : affiche un message d'erreur, aucun changement dans le journal
  [else action annulable]
    B → P : call_tool(undo_function, ref)  [MCP, appel d'exécution]
             ex. remove_handbook(document_ref)
    P → S : supprime/compense l'effet de bord (ex. suppression du fichier PDF
             sur le volume ; pour un e-mail déjà envoyé à MailHog,
             compensation partielle documentée dans TOOLS.md)
    S → P : confirmation
    P → B : résultat de l'annulation
    B → D : met à jour status="undone" + log_audit_event(action_id, "undone")
    B → F : 200 OK  { action_id, status: "undone", undone_at: <timestamp> }
    F → M : affiche l'action comme "annulée" dans le journal, horodatée
  [fin alt]
```

---

## 5. Appel d'un outil réel — palier "Le premier outil"

Ce diagramme détaille ce qui se passe *à l'intérieur* de `A → P : call_tool(...)`
du diagramme 3, maintenant que les outils font de vrais appels (et non plus
un mock) et qu'il en existe **au moins deux** parmi lesquels le LLM doit
choisir. Il illustre trois exigences du palier : le choix de l'outil se
fait par le LLM (jamais par un `if` côté code), une panne d'outil est
rapportée honnêtement (jamais inventée), et chaque appel doit être traçable
en moins de 30 secondes.

Nouveauté par rapport aux diagrammes précédents : `send_welcome_message`
ne prend plus un `recipient` en texte libre (le LLM inventerait une adresse
e-mail) mais un `team`. C'est l'outil, côté P, qui résout `team` en liste
de destinataires réels via un annuaire statique — voir
`employees_directory.json` (fixtures factices, décrites plus bas et dans
`TOOLS.md`). Si l'équipe n'existe pas dans l'annuaire, l'outil renvoie une
erreur plutôt qu'une adresse inventée.

```
M → F : saisit "Préviens l'équipe Backend que Camille commence lundi
         et ouvre un ticket de suivi pour son onboarding."

[... reprend le diagramme 2 jusqu'à l'appel Ollama ...]

A → P : list_tools()  [lecture seule]
P → A : schéma des tools disponibles, ex. :
         - send_welcome_message(employee_name, team, channel) -- side effect
         - create_onboarding_issue(employee_name, start_date, checklist) -- side effect

A → L : prompt + schéma des tools (function-calling / JSON strict)
L → A : { actions: [
           {tool: "send_welcome_message",
            params: {employee_name: "Camille", team: "Backend", channel: "team"}},
           {tool: "create_onboarding_issue",
            params: {employee_name: "Camille", start_date: "2026-08-24",
                      checklist: [...]}}
         ] }

Remarque : c'est le LLM qui choisit ces deux outils en lisant leurs
descriptions + la demande de M -- aucune règle "si le mot 'préviens'
apparaît alors send_welcome_message" côté code.

[... backend persiste les 2 actions en "proposed", M les valide ...]

F → B : POST /plans/{plan_id}/execute

  [loop pour chaque action approuvée]
    B → A : dispatch { action_id, tool, params }
    A → P : call_tool(tool, params)  [MCP, appel d'exécution]

    [alt tool = "send_welcome_message"]
      P → P : lit employees_directory.json, résout team="Backend"
               selon channel ("team" -> tous les membres,
               "manager" -> manager_email, "it" -> équipe IT fixe)
      [alt équipe absente de l'annuaire]
        P → A : erreur ("équipe 'Backend' inconnue de l'annuaire")
      [sinon]
        P → S : SMTP send(to=[emails résolus], ...)  -- MailHog
        S → P : accusé d'envoi
        P → A : MessageRef{ recipients: [...], sent_at }
      [fin alt]
    [fin alt]

    [alt tool = "create_onboarding_issue"]
      [alt outil débranché / indisponible]
        P → A : erreur (connexion refusée / timeout)
      [sinon]
        P → S : crée l'issue
        S → P : IssueRef{ id, ... }
        P → A : IssueRef{ id, ... }
      [fin alt]
    [fin alt]

    A → B : { action_id, status: "executed" | "error", result | note }
    B → D : log_audit_event(action_id, status, note)  -- TOUJOURS, succès ou erreur
  [fin loop]

B → F : 200 OK { results: [...] }
F → M : affiche le résultat par action (✅ exécuté / ❌ erreur + message),
         et le détail de chaque call_tool() dans le panneau debug
```

Traçabilité (exigence du palier — "30 secondes pour montrer la séquence") :
chaque ligne `A → B : { action_id, status, ... }` correspond à une ligne
`AuditLog` déjà persistée (voir `models.py`) et à une ligne de la table
`Action` (`tool`, `params`, `result`, `status`). `GET /audit` les expose
déjà côté backend. Il manque encore un affichage de cette séquence côté
frontend (panneau debug Streamlit) -- à construire avec les deux outils,
pas après.
