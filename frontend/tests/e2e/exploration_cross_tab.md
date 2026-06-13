# E2E manuel — Invalidation cross-onglets Exploration ↔ Graphe ADG-M (T3-T-03)

> Référence : `notebooklm-azure/docs/specs/PLAN_EXPLORATION_v1.md` TÂCHE-3-T-03.
> Pas d'outillage Playwright dans ce projet (pas de build step / npm) — checklist
> manuelle documentée, conformément au critère d'acceptation alternatif de la tâche.

## Prérequis

1. Backend local démarré : `.\start-dev.ps1` (ou `uvicorn api.main:app --reload`)
   — sert `frontend/` et proxy `/api/graph/*`.
2. Ouvrir `http://127.0.0.1:8000`, console DevTools ouverte (onglet Console).
3. Sélecteur de rôle réglé sur **ARCHITECT**.

## Scénario — création de nœud

### 1. Ouvrir l'onglet Graphe ADG-M

- Cliquer sur l'onglet **Graphe ADG-M** (Header).
- ✅ Attendu : le graphe se charge (nœuds/arcs visibles).
- Noter le nombre de nœuds affichés (ex. via le compteur d'éléments si présent,
  sinon compter visuellement / via `data["total"]` dans l'onglet Réseau de la
  requête `GET /api/graph/nodes`).

### 2. Basculer vers Exploration et créer un nœud

- Cliquer sur l'onglet **Exploration**.
- Section **Nœuds** → **"+ Nouveau nœud"**.
- Couche = `Business`, Type = `BusinessActor`, Nom = `E2E Cross-Tab Test`.
- Cliquer **Enregistrer**.
- ✅ Attendu : pas d'erreur console ; redirection vers le détail du nœud créé ;
  un événement `adgm:graph-changed` est émis sur `window` (vérifiable en posant
  un breakpoint ou `window.addEventListener('adgm:graph-changed', console.log)`
  dans la console avant l'étape).

### 3. Revenir sur Graphe ADG-M sans F5

- Cliquer sur l'onglet **Graphe ADG-M** (ne pas recharger la page).
- ✅ Attendu : une requête `GET /api/graph/nodes` (et `/arcs`) est automatiquement
  relancée (visible dans l'onglet Réseau, déclenchée par l'incrément de
  `refreshKey` suite à `adgm:graph-changed`) ; le nœud `E2E Cross-Tab Test`
  apparaît dans le graphe (sous le plan "Business" / "Global"), sans rechargement
  manuel de la page.

## Variante — suppression

- Depuis Exploration, supprimer le nœud `E2E Cross-Tab Test` (Supprimer →
  Confirmer).
- Basculer sur Graphe ADG-M sans F5.
- ✅ Attendu : le nœud disparaît du graphe après le refetch automatique.

## Variante — bulk tag

- Depuis Exploration, sélectionner un ou plusieurs nœuds dans **Nœuds** (cases à
  cocher) et ajouter un tag via la barre de sélection.
- Basculer sur Graphe ADG-M sans F5.
- ✅ Attendu : refetch automatique déclenché (requête réseau visible), pas
  d'erreur console — le contenu du graphe peut être inchangé visuellement (les
  tags ne sont pas nécessairement représentés graphiquement), mais le refetch
  doit avoir lieu.

## Critère d'acceptation global

Après chaque mutation Exploration (création, suppression, bulk-tag), la bascule
vers l'onglet Graphe ADG-M déclenche un refetch automatique de `/graph/nodes` et
`/graph/arcs` sans rechargement de page (F5), et les changements sont visibles
dans le graphe.
