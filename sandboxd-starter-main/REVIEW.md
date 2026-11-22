
# Revue croisée : contrat OpenAPI de sandboxd
 
- **Auteurs du contrat** : Karl JEAN / Anas Louraibi
- **Relecteurs** : Karl JEAN / Anas Louraibi
- **Version relue** : rendu de `make docs` (Redoc)
- **Vérification finale** : `make lint` sans erreur
## Remarques recues
 
### 1. Asynchrone et codes : l'en-tete d'idempotence est faux et la création est mal décrite
 
- **Remarque** : sur `POST /v1/sandboxes`, l'en-tête facultatif s'appelle `keyd` dans le rendu au lieu de `Idempotency-Key`. Aucun client ne l'enverrait sous ce nom. La description de l'opération est aussi tronquée : elle ne dit plus que la création est asynchrone, ni que la sandbox naît en `pending`, ni qu'il faut suivre `Location`. Enfin, rien n'indique ce que renvoie un rejeu : `200` ou `202` ?
- **Où** : `POST /v1/sandboxes` (paramètres et description)
- **Décision** : corrigé
- **Ce que j'ai changé** :
  - Le paramètre d'en-tête s'appelle de nouveau `Idempotency-Key`, avec sa description.
  - La description de `createSandbox` explique l'asynchronisme (`pending`, puis `ready` ou `failed`, suivi via `Location`).
  - Elle précise qu'un rejeu renvoie la même réponse `202` (même corps, même `Location`) et qu'une clé réutilisée avec un corps différent donne `409`.
### 2. Fichiers : `writeFile` ne dit pas ce qui se passe pour `../`, un dossier ou un parent absent
 
- **Remarque** : la description de `PUT .../files` s'arrête à « remplace son contenu ». Le cas d'un chemin absolu, d'un `..` ou d'un dossier n'est pas traité, alors que `readFile` le traite. On ne sait pas non plus quel code renvoyer quand le dossier parent n'existe pas.
- **Où** : `PUT /v1/sandboxes/{sandbox_id}/files`
- **Décision** : corrigé
- **Ce que j'ai changé** : la description de `writeFile` fixe maintenant les règles.
  - Chemin désignant un dossier, absolu ou contenant `..` : `400`.
  - Dossier parent absent : `404`.
  - Sandbox pas encore prête : `409`.
  - Création : `201`. Remplacement : `204`.
  Le paramètre `path` reste relatif à `/workspace`.
### 3. Ambiguïté : `404` ne dit pas si c'est la sandbox ou le fichier qui manque
 
- **Remarque** : la même réponse `404` sert à la sandbox absente et au fichier absent. Deux équipes pourraient donc coder deux comportements différents, et le client ne sait pas quoi corriger. Les petits défauts de forme (accents perdus dans les tags « Lecture et ecriture », « Sondes de sante ») gênent aussi la lecture du rendu.
- **Où** : réponse `NotFound` réutilisée par `getSandbox`, `execCommand`, `readFile` et `writeFile`
- **Décision** : corrigé en partie
- **Ce que j'ai changé** :
  - Les accents des tags sont rétablis.
  - Le `404` reste commun pour garder un contrat simple. Le champ `detail` du problem+json nomme la ressource manquante (`sbx-... n'existe pas`, ou le chemin du fichier absent).
  - Pas de nouveau code HTTP : la distinction se fait par `type` et `detail`.
  - Une sandbox expirée passe en `terminated` (valeur déjà présente dans `SandboxStatus`).
## Bilan
 
| # | Critère de la grille | Corrigé ? |
|---|----------------------|-----------|
| 1 | Asynchrone, Codes | oui |
| 2 | Fichiers | oui |
| 3 | Ambiguïté | en partie |
 
Au moins deux remarques sur trois sont corrigées avant de coder (TP suivant), et `make lint` passe sans erreur.
 
