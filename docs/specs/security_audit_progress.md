# Audit de sécurité — Progression
*Projet : NotebookLM Azure | Démarré : 2026-06-05*

## PHASE 1 — RECONNAISSANCE ✅

**Stack technique**
- Backend : Python 3.11, FastAPI 0.115.5, Uvicorn, Azure SDK, OpenAI SDK 1.57.0
- Frontend : HTML/CSS/JS vanilla + React 18 (CDN unpkg), Babel standalone (transpile JSX at runtime), marked.js 9, mermaid.js 11
- IaC : Azure Bicep (modules: containerapp, keyvault, openai, search, storage, docint, monitoring, registry)
- Gestionnaires de dépendances : pip / requirements.txt (deux venvs distincts : api/ et ingest/)
- Pas de CI/CD détecté

**Points d'entrée**
- POST /api/chat
- DELETE /api/chat/{session_id}
- POST /api/ingest (upload fichier)
- GET /api/ingest/{job_id}
- GET /health
- Fichiers statiques servis à /

**Assets sensibles**
- 3 fichiers .env (root, api/, ingest/) — contiennent URLs de prod Azure
- infra/main.parameters.json — contient Azure AD Object ID réel
- documents/ — contient des PDFs clients réels (WebEpargne, Politique Sécurité 2023)
- Key Vault URI exposé dans .env files

**Infrastructure**
- Dockerfile : python:3.11-slim, utilisateur non-root (appuser), --workers 2
- Bicep : App Service (httpsOnly: true), Managed Identity, Key Vault, Role Assignments
- Pas de manifest k8s, pas de docker-compose, pas de pipeline CI/CD dans le repo

---

## PHASE 2 — SCAN DE SÉCURITÉ ✅

**Domaine 1 — Dépendances**
- azure-search-documents==11.6.0b8 : version BÊTA en prod (x2 : api + ingest)
- opencensus-ext-azure==1.1.13 : package déprécié (plus maintenu)
- Pas de pip-audit/safety disponibles dans l'environnement Windows — analyse manuelle effectuée

**Domaine 2 — Secrets et credentials**
- Aucune clé API hardcodée détectée (auth via Managed Identity / DefaultAzureCredential ✅)
- URLs de production réelles dans .env.example (oai-nlmazure-prod, srch-nlmazure-prod, etc.)
- Azure AD Object ID réel dans main.parameters.json (10a7d393-4f60-4b54-8d42-ac3a5a5a9adf)
- Documents PDF confidentiels committés dans documents/

**Domaine 3 — OWASP Top 10**
- CRITIQUE : 0 authentification sur aucun endpoint API
- HAUTE : CORS wildcard + allow_credentials=True (api/main.py:72-78)
- HAUTE : XSS via dangerouslySetInnerHTML(marked.parse()) + mermaid securityLevel:'loose' (tokens.jsx:116, index.html:93)
- MOYENNE : messages d'erreur techniques exposés (str(e) → HTTP 503 detail)
- MOYENNE : validation upload par extension uniquement (pas MIME/magic bytes)
- MOYENNE : sessions in-memory incompatibles avec --workers 2

**Domaine 4 — Infrastructure**
- Image Docker non épinglée à un digest SHA
- infra/main.parameters.json contient Object ID réel + valeur prod imageTag placeholder (ok)
- containerapp.bicep : httpsOnly=true ✅, Managed Identity ✅, pas de secrets en ARG ✅

**Domaine 5 — Qualité sécuritaire**
- Librairies CDN sans SRI (React, Babel, Marked, Mermaid)
- Headers sécurité HTTP manquants (CSP, X-Frame-Options, X-Content-Type-Options)
- Session IDs exposés en URL (DELETE /api/chat/{session_id})
- Math.random() pour uid() — non-cryptographique (usage non-sécuritaire ici : IDs affichage seulement)

---

## PHASE 3 — RAPPORT D'AUDIT ✅
→ Fichier : SECURITY_AUDIT.md (15 findings, 1 CRITIQUE / 3 HAUTE / 7 MOYENNE / 4 FAIBLE)

## PHASE 4 — PLAN DE REMÉDIATION ✅
→ Fichier : REMEDIATION_PLAN.md (4 vagues, 15 tâches)

## REMÉDIATION EXÉCUTÉE ✅ (2026-06-05)

### Vague 1 — Nettoyage immédiat
- [x] T-001 : PDFs WebEpargne supprimés de documents/ ; .gitignore étendu (documents/*.pdf, infra/main.parameters.json)
- [x] T-002 : .env.example remplacé par des placeholders ; ajout de API_KEY template
- [x] T-003 : deployerObjectId remplacé par <DEPLOYER_OBJECT_ID> dans main.parameters.json
- [x] T-004 : azure-search-documents 11.6.0b8 → 12.0.0 (api + ingest)
- [x] T-005 : opencensus-ext-azure supprimé → azure-monitor-opentelemetry==1.8.8

### Vague 2 — Corrections de code
- [x] T-006 : SecurityHeadersMiddleware (CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy) ajouté à api/main.py
- [x] T-007 : Messages d'erreur génériques dans chat.py et ingest.py ; logger.exception() pour les détails internes
- [x] T-008 : Validation magic bytes (_check_magic_bytes) dans ingest.py — vérification %PDF / PK\x03\x04 / UTF-8
- [x] T-009 : Dockerfile épinglé sur python:3.11-slim@sha256:02ebabf8...

### Vague 3 — Refontes structurantes
- [x] T-010 : APIKeyMiddleware (secrets.compare_digest) implémenté dans api/main.py ; variable API_KEY
- [x] T-011 : DOMPurify.sanitize() dans tokens.jsx (marked.parse + SVG Mermaid) ; securityLevel:'strict' dans index.html et app.js
- [x] T-012 : CORS restreint à CORS_ALLOWED_ORIGINS (env var) ; allow_credentials=False ; méthodes listées explicitement
- [x] T-013 : 6 libs JS vendorisées localement dans frontend/vendor/ (react, react-dom, babel, marked, mermaid, dompurify)

### Vague 4 — Durcissement
- [x] T-014 : Sessions avec TTL 24h + cleanup automatique (get_or_create_session)
- [x] T-015 : DELETE /api/chat/{session_id} → POST /api/chat/clear avec body JSON ; App.jsx et app.js mis à jour

### Fichiers modifiés
- notebooklm-azure/.gitignore
- notebooklm-azure/.env.example
- notebooklm-azure/infra/main.parameters.json
- notebooklm-azure/api/requirements.txt
- notebooklm-azure/ingest/requirements.txt
- notebooklm-azure/api/main.py
- notebooklm-azure/api/routers/chat.py
- notebooklm-azure/api/routers/ingest.py
- notebooklm-azure/api/Dockerfile
- notebooklm-azure/frontend/index.html
- notebooklm-azure/frontend/app.js
- notebooklm-azure/frontend/src/tokens.jsx
- notebooklm-azure/frontend/src/App.jsx
- notebooklm-azure/frontend/vendor/ (6 fichiers créés)
- documents/*.pdf (4 fichiers supprimés)
