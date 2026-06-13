# E2E manuel — Création de relation avec avertissement ArchiMate (T2-T-03)

> Référence : `notebooklm-azure/docs/specs/PLAN_EXPLORATION_v1.md` TÂCHE-2-T-03.
> Pas d'outillage Playwright dans ce projet (pas de build step / npm) — checklist
> manuelle documentée, conformément au critère d'acceptation alternatif de la tâche.

## Prérequis

1. Backend local démarré : `.\start-dev.ps1` (ou `uvicorn api.main:app --reload` sur
   le port souhaité) — sert `frontend/` et proxy `/api/graph/exploration/*` vers
   `fn-adgm-graph` (AuraDB distant, cf. `CLAUDE.md`).
2. Graphe seedé via `seed_exploration_graph` / `exploration_seed.cypher` (les nœuds
   `Souscrire Contrat` et `Contrat Signé` doivent exister, `seedTest: true`).
3. Ouvrir `http://127.0.0.1:8000` dans un navigateur, console DevTools ouverte
   (onglets Console + Réseau) pour surveiller les erreurs JS/réseau.
4. Onglet **Exploration** (Header) → sélecteur de rôle en haut à droite réglé sur
   **ARCHITECT**.

## Scénario

### 1. Ouvrir le détail du nœud source

- Section **Nœuds** → filtrer/rechercher `Souscrire Contrat` (layer Business,
  aspect `Behaviour`, donc **non-ActiveStructure**).
- Cliquer **"Voir"**.
- ✅ Attendu : vue détail affiche `aspect: Behaviour`, section "Relations (N)".

### 2. Lancer la création d'une relation depuis le détail

- Cliquer **"+ Nouvelle relation"** dans l'en-tête de la section Relations.
- ✅ Attendu : `RelFormView` (mode création) s'ouvre, le nœud source est
  pré-rempli avec `Souscrire Contrat` (sélecteur source verrouillé/pré-sélectionné).

### 3. Configurer la relation Assignment

- Type de relation = `Assignment`.
- Cible = `Contrat Signé` (Business, aspect non-`ActiveStructure` également —
  cohérent avec le cas positif VAL-05 de `test_exploration_validation.py`).
- Cliquer **Enregistrer**.

### 4. Vérifier l'avertissement VAL-05

- ✅ Attendu : la requête `POST /api/graph/exploration/relations` répond `422`
  avec `code: "ARCHIMATE_WARN"` et un avertissement `VAL_ASSIGNMENT_ASPECT`
  (visible dans l'onglet Réseau).
- ✅ Attendu côté UI : le formulaire reste ouvert, affiche le badge
  d'avertissement (🟡 WARN — "Assignment depuis un élément non-ActiveStructure")
  et fait apparaître la case **"Créer quand même"** (`confirmWarnings`).
- ✅ Attendu : le bouton Enregistrer est désactivé tant que la case n'est pas
  cochée (`submitBlocked`).

### 5. Confirmer malgré l'avertissement

- Cocher **"Créer quand même"**.
- Cliquer **Enregistrer**.
- ✅ Attendu : la requête `POST /api/graph/exploration/relations` est renvoyée
  avec `confirmWarnings: true` dans le corps, réponse `201`.
- ✅ Attendu : retour à la vue détail du nœud `Souscrire Contrat`, la nouvelle
  relation `Assignment → Contrat Signé` apparaît dans la liste "Relations",
  sans erreur console.

### 6. Nettoyage

- Sur la ligne de la relation créée, cliquer **Supprimer** → confirmer dans
  `DeleteRelationConfirmModal`.
- ✅ Attendu : `DELETE /api/graph/exploration/relations/{id}` → `200`, la
  relation disparaît de la liste.

## Critère d'acceptation global

Scénario complet (étapes 1-6) sans erreur console ; badge VAL-05 correctement
affiché à l'étape 4 ; requête de confirmation envoyée avec `confirmWarnings: true`
à l'étape 5 ; relation visible puis supprimable depuis `NodeDetailView`.
