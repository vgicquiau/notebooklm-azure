# E2E manuel — Gestion des erreurs API (T4-F-02)

> Référence : `notebooklm-azure/docs/specs/PLAN_EXPLORATION_v1.md` TÂCHE-4-F-02,
> `SDD_Exploration_v1.md` §7. Pas d'outillage Playwright dans ce projet — checklist
> manuelle documentée, conformément au critère d'acceptation alternatif de la tâche.

## Prérequis

1. Backend local démarré : `.\start-dev.ps1`.
2. Ouvrir `http://127.0.0.1:8000` → onglet **Exploration**, console DevTools ouverte
   (onglets Console + Réseau).
3. Sélecteur de rôle réglé sur **ARCHITECT** (sauf variante explicite).

## Scénario — 503 / erreur réseau + bouton Réessayer (critère d'acceptation principal)

1. Section **Nœuds** chargée normalement.
2. Couper le réseau (DevTools → Network → Offline, ou arrêter `start-dev.ps1`).
3. Cliquer le bouton **Rafraîchir** (icône ↻) de la liste.
4. ✅ Attendu :
   - Une bannière rouge inline apparaît avec le message
     « Connexion impossible — vérifiez votre réseau et réessayez » (ou « Base de
     données temporairement indisponible — réessayez » si le backend répond 503)
     et un bouton **Réessayer**.
   - Un toast rouge identique apparaît en bas à droite (`ToastStack`), disparaît
     automatiquement après ~6 s ou via le bouton **×**.
5. Rétablir le réseau, cliquer **Réessayer**.
6. ✅ Attendu : la bannière et le toast disparaissent, la liste se recharge
   normalement.

## Variante — 404 sur le détail d'un nœud

1. Ouvrir le détail d'un nœud (`GET /exploration/nodes/{id}`).
2. Dans un autre onglet/rôle ADMIN, supprimer ce nœud (ou modifier l'URL pour un id
   inexistant et naviguer directement).
3. Revenir sur l'onglet détail et rafraîchir (`refreshKey` ou navigation directe
   vers un id inconnu).
4. ✅ Attendu : toast rouge « Nœud introuvable » (ou message équivalent), retour
   automatique à la liste des nœuds — pas d'écran bloqué sur l'erreur.

## Variante — 403 sur un formulaire (rôle insuffisant en cours de session)

1. Ouvrir **"+ Nouveau nœud"** en ARCHITECT.
2. Repasser le sélecteur de rôle sur **VIEWER** sans fermer le formulaire.
3. Renseigner les champs et cliquer **Enregistrer**.
4. ✅ Attendu : toast rouge « Opération non autorisée pour votre rôle » (ou message
   backend équivalent), le formulaire se ferme et retourne à la liste — pas de
   bannière bloquante dans le formulaire fermé.

## Variante — 429 (rate limit, si activé)

- Si le rate limiting est activé côté backend (non implémenté par défaut, cf.
  SDD §7), déclencher >100 requêtes/min sur `/exploration/*`.
- ✅ Attendu : toast « Trop de requêtes — réessayez dans {s} secondes » si l'en-tête
  `Retry-After` est présent, sinon « Trop de requêtes — réessayez plus tard ».

## Critère d'acceptation global

Aucune erreur API ne produit d'écran blanc ni d'exception JS non interceptée
(vérifier la console) : chaque cas (403/404/429/500/503/réseau) se traduit par un
toast et, pour les listes/détails, une bannière inline avec bouton Réessayer quand
pertinent (500/503/réseau).
