# Plan de remédiation — NotebookLM Azure
*Basé sur l'audit du 2026-06-05 | 15 findings | Durée estimée totale : ~5 jours*

---

## Logique de parallélisation

La Vague 1 regroupe les actions sans dépendances de code : suppression de fichiers committés et mise à jour de dépendances — exécutables simultanément par des profils différents. La Vague 2 adresse les corrections de code indépendantes entre elles : chaque tâche touche un fichier ou un module distinct (headers HTTP, validation MIME, erreurs, sessions), ce qui permet une parallélisation totale entre développeurs. La Vague 3 implémente l'authentification, qui dépend de la Vague 2 car elle doit englober les routes corrigées, et la correction XSS/Mermaid qui nécessite une décision préalable sur le choix de DOMPurify vs bundling (résultat de la Vague 2 sur les CDN). La Vague 4 couvre le durcissement final et les bonnes pratiques applicables une fois les vulnérabilités actives résolues.

---

## Vague 1 — Nettoyage immédiat sans dépendances de code
> Parallélisable à 100% | Durée estimée : 2-4h | Prérequis : aucun

| ID Tâche | Description de l'action | Finding(s) couverts | Effort | Profil |
|----------|------------------------|---------------------|--------|--------|
| T-001 | Supprimer les PDFs clients de `notebooklm-azure/documents/`, purger l'historique git (`git filter-repo --path notebooklm-azure/documents/ --invert-paths`), ajouter `documents/*.pdf documents/*.docx` au `.gitignore` | SEC-004 | S (<1h) | DevOps |
| T-002 | Remplacer toutes les valeurs de production dans `.env.example` par des placeholders (`<YOUR_RESOURCE_NAME>`), vérifier via `git check-ignore -v api/.env ingest/.env` que ces fichiers sont bien ignorés | SEC-005 | S (<1h) | Dev |
| T-003 | Remplacer la valeur réelle de `deployerObjectId` dans `infra/main.parameters.json` par un placeholder `<DEPLOYER_OBJECT_ID>`, ajouter le fichier au `.gitignore`, créer `main.parameters.example.json` avec le placeholder | SEC-011 | S (<1h) | DevOps |
| T-004 | Remplacer `azure-search-documents==11.6.0b8` par la dernière version stable dans `api/requirements.txt` et `ingest/requirements.txt`, tester le démarrage de l'API et l'ingestion | SEC-012 | S (<1h) | Dev |
| T-005 | Remplacer `opencensus-ext-azure==1.1.13` par `azure-monitor-opentelemetry` dans `api/requirements.txt`, adapter l'instrumentation de monitoring | SEC-014 | M (2-4h) | Dev |

---

## Vague 2 — Corrections de code indépendantes
> Parallélisable entre elles | Durée estimée : 1 journée | Prérequis : Vague 1

| ID Tâche | Description de l'action | Finding(s) couverts | Effort | Profil |
|----------|------------------------|---------------------|--------|--------|
| T-006 | Ajouter un `SecurityHeadersMiddleware` dans `api/main.py` (avant le middleware CORS) injectant `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Content-Security-Policy` | SEC-007 | M (2-4h) | Dev |
| T-007 | Remplacer dans `api/routers/chat.py` (lignes 32-33, 52-53) et `api/routers/ingest.py` (ligne 122) les messages `f"... {e}"` et `str(e)` par des messages génériques, logger l'exception complète côté serveur avec `logger.exception(e)` | SEC-006 | S (<1h) | Dev |
| T-008 | Ajouter la validation par magic bytes dans `api/routers/ingest.py` : installer `python-magic`, vérifier le MIME type des 2048 premiers octets du contenu uploadé avant traitement | SEC-010 | M (2-4h) | Dev |
| T-009 | Remplacer `FROM python:3.11-slim` par `FROM python:3.11-slim@sha256:<digest>` dans `api/Dockerfile`, documenter la procédure de mise à jour du digest | SEC-013 | S (<1h) | DevOps |

---

## Vague 3 — Refontes structurantes (dépendent des Vagues 1 et 2)
> Parallélisable entre T-010 et T-011 | Durée estimée : 2 jours | Prérequis : Vagues 1 et 2

| ID Tâche | Description de l'action | Finding(s) couverts | Effort | Profil |
|----------|------------------------|---------------------|--------|--------|
| T-010 | **Authentification API** : implémenter `fastapi-azure-auth` (ou middleware JWT Entra ID) sur toutes les routes `/api/*`. Configurer une App Registration Azure AD, protéger `POST /api/chat`, `POST /api/ingest`, `GET /api/ingest/{job_id}`, `DELETE /api/chat/{session_id}`. Mettre à jour le frontend pour inclure le Bearer token dans les requêtes. | SEC-001 | L (1-2j) | Dev + Azure |
| T-011 | **Correction XSS** : (a) Installer DOMPurify (`npm install dompurify` ou via CDN avec SRI) ; (b) appliquer `DOMPurify.sanitize()` sur le HTML produit par `marked.parse()` dans `tokens.jsx:84` avant injection dans `dangerouslySetInnerHTML` ; (c) passer Mermaid en `securityLevel: 'strict'` dans `index.html:93` et `app.js:15` ; (d) remplacer `wrapper.innerHTML = svg` par une insertion DOM sûre via `DOMParser` | SEC-002 | M (2-4h) | Dev Front |
| T-012 | **Correction CORS** : restreindre `allow_origins` dans `api/main.py` à la liste des origines légitimes (URL du Container App), supprimer `allow_credentials=True` si le frontend est co-hébergé, supprimer `allow_methods=["*"]` pour lister uniquement les méthodes utilisées | SEC-003 | S (<1h) | Dev |
| T-013 | **Ajout SRI + dépendances CDN** : générer les hash SHA384 des 5 bibliothèques CDN et ajouter les attributs `integrity=` dans `index.html`. Alternative recommandée : migrer vers un build Vite pour bundler localement et éliminer les CDN. | SEC-008 | M (2-4h) | Dev Front |

---

## Vague 4 — Durcissement et bonnes pratiques
> Durée estimée : 4h | Prérequis : Vagues 1, 2 et 3

| ID Tâche | Description de l'action | Finding(s) couverts | Effort | Profil |
|----------|------------------------|---------------------|--------|--------|
| T-014 | **Sessions persistantes** : remplacer le dict in-memory `_sessions` par Azure Cache for Redis (ou Redis local en dev), ajouter un TTL de 24h par session, lier le session_id à l'identité de l'utilisateur authentifié (après T-010) | SEC-009 | L (1j) | Dev |
| T-015 | **Session ID hors URL** : renommer `DELETE /api/chat/{session_id}` en `POST /api/chat/clear` avec le session_id dans le body JSON, mettre à jour le frontend (`App.jsx:271`, `app.js:192`) | SEC-015 | S (<1h) | Dev |

---

## Vue synthétique : risque éliminé par vague

| Vague | Nb tâches | Findings adressés | Risque éliminé | Durée est. |
|-------|-----------|-------------------|----------------|------------|
| Vague 1 | 5 | SEC-004, SEC-005, SEC-011, SEC-012, SEC-014 | 🟠×1, 🟡×2, 🔵×2 | 4-6h |
| Vague 2 | 4 | SEC-006, SEC-007, SEC-010, SEC-013 | 🟡×3, 🔵×1 | 1j |
| Vague 3 | 4 | SEC-001, SEC-002, SEC-003, SEC-008 | 🔴×1, 🟠×2, 🟡×1 | 2j |
| Vague 4 | 2 | SEC-009, SEC-015 | 🟡×1, 🔵×1 | 4h |
| **Total** | **15** | **Tous (SEC-001 à SEC-015)** | **🔴×1, 🟠×3, 🟡×7, 🔵×4** | **~5j** |

---

## Notes d'implémentation

**T-001 — Purge historique git** : Si le dépôt est hébergé sur GitHub/Azure DevOps, un force-push sera nécessaire après `git filter-repo`. Coordonner avec tous les contributeurs pour qu'ils re-clonent le dépôt. Considérer les documents comme potentiellement compromis si le dépôt a été partagé ou poussé sur une plateforme distante.

**T-010 — Authentification** : Choisir entre (a) Azure Entra ID + `fastapi-azure-auth` (recommandé pour un déploiement Azure) ou (b) API Key statique stockée en Key Vault (solution minimale rapide). Option (a) prend 1-2 jours mais est la solution pérenne. Le frontend devra utiliser MSAL.js pour acquérir le token.

**T-011 — XSS + Mermaid** : La migration vers un build Vite (T-013) simplifie T-011 car DOMPurify peut être importé comme module npm plutôt que chargé via CDN. Envisager de traiter T-011 et T-013 en séquence par le même développeur.
