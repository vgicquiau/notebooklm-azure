# NotebookLM Azure — Guide d'utilisation

*Ce guide est écrit pour les utilisateurs de l'application, sans connaissances techniques.
Si vous devez installer ou déployer l'application, ce n'est pas le bon document — voir
[GUIDE-DEPLOIEMENT.md](GUIDE-DEPLOIEMENT.md), destiné à la personne qui s'occupe de la
technique.*

---

## 1. C'est quoi, cette application ?

NotebookLM Azure est un assistant qui répond à vos questions **à partir de vos propres
documents**. Vous déposez vos fichiers (PDF, Word, Excel, PowerPoint…), vous posez une
question en français, et l'assistant vous répond en citant précisément où il a trouvé
l'information dans vos documents — comme un collègue qui aurait tout lu à votre place.

Elle inclut aussi une deuxième fonctionnalité, **Legacy KB** : une carte interactive d'une
application informatique existante (un "mainframe"), pour comprendre comment ses programmes
sont reliés entre eux sans avoir à lire le code.

---

## 2. Démarrer l'application

Quelqu'un de votre équipe a déjà préparé l'application sur votre ordinateur. Pour la lancer :

**Option la plus simple** : double-cliquez sur le fichier **`Lancer-NotebookLM.bat`** à la
racine du dossier du projet. Une fenêtre noire s'ouvre (c'est normal, c'est le moteur de
l'application qui démarre) et votre navigateur internet s'ouvre automatiquement sur la page
de l'application après quelques secondes.

> Si rien ne s'ouvre automatiquement, ouvrez vous-même votre navigateur et allez à l'adresse :
> `http://127.0.0.1:8000`

**Pour arrêter l'application** : fermez la fenêtre noire, ou cliquez dedans et appuyez sur
`Ctrl + C`.

> **Ne fermez pas la fenêtre noire pendant que vous utilisez l'application** — c'est elle qui
> fait fonctionner tout le reste. Si vous la fermez, la page web cesse de répondre, mais vous
> pouvez relancer `Lancer-NotebookLM.bat` à tout moment.

---

## 3. Utiliser le Chat — poser des questions sur vos documents

### 3.1 Ajouter des documents

1. À gauche de l'écran se trouve le rail **Sources**.
2. Cliquez sur le bouton d'ajout (icône **+**) et choisissez un ou plusieurs fichiers sur
   votre ordinateur.
3. Formats acceptés : PDF, Word (`.docx`), PowerPoint (`.pptx`), Excel (`.xlsx`), Markdown
   (`.md`), texte brut (`.txt`), et la plupart des formats de code source.
4. Patientez quelques secondes à quelques minutes selon la taille du document — une barre de
   progression indique l'état de l'ajout ("ingestion").
5. Une fois ajouté, le document apparaît dans la liste des sources et devient interrogeable
   par le Chat.

Pour **retirer** un document de l'assistant (il ne sera plus utilisé pour répondre), cliquez
sur l'icône de suppression à côté de son nom dans le rail Sources. Cela ne supprime pas le
fichier sur votre ordinateur, seulement la copie indexée par l'application.

### 3.2 Poser une question

1. Tapez votre question dans la zone de texte en bas de l'écran et validez.
2. L'assistant répond en quelques secondes, avec des petites références numérotées entre
   crochets, par exemple **[1]**, **[2]**.
3. **Cliquez sur une référence** pour voir exactement le passage du document d'où vient
   l'information — utile pour vérifier la réponse ou retrouver le contexte complet.

### 3.3 Choisir un mode de réponse

Trois modes sont disponibles au-dessus de la zone de question :

| Mode | Quand l'utiliser |
|---|---|
| **Rapide** | Question simple, vous voulez une réponse immédiate |
| **Standard** | Mode par défaut, bon équilibre vitesse/précision |
| **Approfondi** | Question complexe nécessitant de croiser beaucoup de passages dans vos documents |

### 3.4 Les notes

Le rail à droite de l'écran permet de **conserver des informations utiles** :

- Cliquez sur **"Ajouter une note"** pour écrire vous-même une note libre.
- Depuis une réponse de l'assistant, vous pouvez l'enregistrer comme note pour la retrouver
  plus tard.
- Une note peut elle-même être **indexée comme source** (bouton dédié) : l'assistant pourra
  alors s'en servir pour répondre à de futures questions, exactement comme un document
  importé.

---

## 4. Utiliser Legacy KB — explorer la carte de l'application mainframe

1. En haut de l'écran, cliquez sur **"Legacy KB"** pour basculer depuis le Chat.
2. Une barre de recherche permet de trouver un programme, un fichier ou un domaine
   fonctionnel par son nom (ex. `RE1570`).
3. Cliquez sur un résultat pour voir sa fiche détaillée (description, domaine
   d'appartenance…).
4. **Double-cliquez sur un nœud** du graphe pour afficher tout ce qui lui est directement
   relié (programmes qui l'appellent, fichiers qu'il utilise…) et continuer à explorer de
   proche en proche.
5. Vous pouvez aussi poser vos questions sur cette application mainframe directement dans le
   **Chat** (onglet "Chat") — l'assistant va lui-même chercher dans cette carte pour vous
   répondre, sans que vous ayez besoin d'aller sur la vue Legacy KB.

> Si la vue Legacy KB affiche une erreur ou reste vide, voir la section Dépannage ci-dessous.

---

## 5. Dépannage — problèmes courants

| Ce que vous voyez | Que faire |
|---|---|
| Le navigateur affiche "Cette page est inaccessible" | L'application n'est pas démarrée — relancez `Lancer-NotebookLM.bat` (§2) |
| La fenêtre noire s'est fermée toute seule | Relancez `Lancer-NotebookLM.bat`. Si ça se reproduit, contactez la personne qui gère l'application technique |
| Un document reste bloqué sur "en cours d'ingestion" très longtemps | Les gros PDF scannés peuvent prendre plusieurs minutes — patientez. Au-delà de 10 minutes, retirez le document et réessayez |
| L'assistant répond "je ne trouve pas l'information" | Vérifiez que le document concerné est bien présent dans le rail Sources, et reformulez votre question de façon plus précise |
| La vue Legacy KB affiche un voyant rouge "injoignable" ou des erreurs dans la page | Limitation connue en local : la base Legacy KB n'est accessible qu'à distance, votre poste n'a pas accès direct. Le Chat (onglet "Chat") continue de fonctionner normalement pour les questions sur le mainframe — privilégiez-le |
| Rien ne se passe quand je double-clique sur `Lancer-NotebookLM.bat` | Windows peut afficher un avertissement de sécurité la première fois — cliquez sur "Informations complémentaires" puis "Exécuter quand même". Si le problème persiste, contactez la personne qui gère l'application technique |

**Si rien de tout cela ne résout votre problème**, contactez la personne qui a installé
l'application pour vous — elle trouvera plus de détails techniques dans
[GUIDE-DEPLOIEMENT.md](GUIDE-DEPLOIEMENT.md) (section "Troubleshooting").
