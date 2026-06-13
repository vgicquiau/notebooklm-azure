# E2E manuel — Cycle de vie d'un nœud (T1-T-03)

> Référence : `notebooklm-azure/docs/specs/PLAN_EXPLORATION_v1.md` TÂCHE-1-T-03.
> Pas d'outillage Playwright dans ce projet (pas de build step / npm) — checklist
> manuelle documentée, conformément au critère d'acceptation alternatif de la tâche.

## Prérequis

1. Backend local démarré : `.\start-dev.ps1` (ou `uvicorn api.main:app --reload` sur
   le port souhaité) — sert `frontend/` et proxy `/api/graph/exploration/*` vers
   `fn-adgm-graph` (AuraDB distant, cf. `CLAUDE.md`).
2. Ouvrir `http://127.0.0.1:8000` dans un navigateur, console DevTools ouverte
   (onglet Console) pour surveiller les erreurs JS/réseau.
3. Onglet **Exploration** (Header) → sélecteur de rôle en haut à droite réglé sur
   **ARCHITECT** (création/édition/suppression requièrent ARCHITECT ou ADMIN).

## Scénario

### 1. Création — nœud Business/BusinessActor
- Aller dans la section **Nœuds**, cliquer **"+ Nouveau nœud"**.
- Couche = `Business` → Type se met à jour automatiquement sur la première valeur
  (`BusinessActor`) ; vérifier que la liste des types proposés correspond bien à
  `ARCHIMATE_ELEMENT_TYPES_BY_LAYER.Business`.
- Renseigner **Nom** = `E2E Acteur Test` (laisser Description/Aspect/Tags/Stéréotype
  vides ou renseigner librement).
- Cliquer **Enregistrer**.
- ✅ Attendu : pas d'erreur console ; redirection vers la vue détail du nœud créé ;
  le nœud affiche `elementType=BusinessActor`, `layer=Business`, 0 relation.

### 2. Retrouver le nœud dans la liste (filtre layer)
- Cliquer **"← Retour à la liste"**.
- Filtrer **Layer = Business**.
- ✅ Attendu : `E2E Acteur Test` apparaît dans le tableau, colonne "Relations" = 0 ;
  requête déclenchée à chaque changement de filtre (vérifier dans l'onglet
  Réseau : `GET /api/graph/exploration/nodes?layer=Business&...`).

### 3. Ouvrir le détail
- Cliquer **"Voir"** sur la ligne `E2E Acteur Test`.
- ✅ Attendu : propriétés affichées (id, description vide → `—`, dates de création/
  modification identiques), sections "Relations (0)" vide.

### 4. Modifier la description
- Cliquer **Modifier**.
- ✅ Attendu : Couche/Type désactivés (immuables en édition) ; champ Nom pré-rempli.
- Modifier **Description** = `Modifié via E2E`.
- Cliquer **Enregistrer**.
- ✅ Attendu : retour à la vue détail, `Description` affiche `Modifié via E2E`,
  `Modifié le` mis à jour (différent de `Créé le`), `id`/`Créé le` inchangés.

### 5. Suppression (safe, 0 relation)
- Cliquer **Supprimer**.
- ✅ Attendu : modal de confirmation affiche le nom/type/layer du nœud, pas
  d'avertissement de relations (relCount=0), pas de case "cascade" (réservée
  ADMIN + relCount>0).
- Confirmer.
- ✅ Attendu : retour à la liste, `E2E Acteur Test` n'apparaît plus (filtre Layer=
  Business toujours actif) ; aucune erreur console.

## Variante — suppression bloquée (409)

- Ouvrir le détail d'un nœud du seed possédant des relations (ex. "Souscrire
  Contrat" si le seed `exploration_seed.cypher` est chargé sur l'instance utilisée).
- Cliquer **Supprimer** → confirmer.
- ✅ Attendu : message d'erreur inline `NODE_HAS_RELATIONS` avec le nombre de
  relations, la modale reste ouverte, le nœud n'est pas supprimé.

## Variante — rôle VIEWER

- Repasser le sélecteur de rôle sur **VIEWER**.
- ✅ Attendu : boutons "+ Nouveau nœud", "Modifier", "Supprimer" masqués sur la
  liste/détail ; section **Orphelins** (réservée ARCHITECT/ADMIN côté API) renvoie
  une erreur 403 si on tente d'y accéder — vérifier l'affichage du message d'erreur
  (`ErrorBanner`) plutôt qu'un écran blanc/crash.

## Critère d'acceptation global

Scénario complet (étapes 1-5) sans erreur console, sans requête réseau en échec
(hors 409/403 volontairement exercés dans les variantes), toutes les transitions
de vue (liste ↔ détail ↔ formulaire) cohérentes avec les filtres actifs.
