# TP3 : implémentation de l'API

Binôme : Karl JEAN / Anas Louraibi

## Ce qui est fait

- createSandbox : la sandbox est créée en pending, le conteneur est créé en tâche de fond (provision), réponse 202 + Location.
- listSandboxes : filtre par état, pagination par curseur (page_size, page_token, next_page_token).
- deleteSandbox : supprime le conteneur puis la sandbox. Le 2e DELETE renvoie 404.
- execCommand : 409 si la sandbox n'est pas ready. Une commande qui échoue ou dépasse son timeout renvoie quand même 200.
- readFile / writeFile : les chemins absolus, avec `..` ou qui désignent un dossier sont refusés (400).
- Bonus : Idempotency-Key sur la création (même clé + même corps = même réponse, autre corps = 409).
- Bonus : ETag sur getSandbox et updateSandbox, If-Match sur le PATCH (412 si la version a changé).

## Dernière sortie de make test-contract

```
Schemathesis v4.34.0

 ✅  Loaded specification from openapi.yaml (in 6.33s)
     Operations:       9 selected / 9 total

 ✅  Examples (in 1.55s)
 ✅  Coverage (in 5.17s)      ✅ 9 passed
 ✅  Fuzzing (in 14.75s)      ✅ 9 passed
 ✅  Stateful (in 11.60s)     ✅ 24 passed

Warnings:
  ⚠️ Schema validation mismatch: 1 operation mostly rejected generated data
     - PATCH /v1/sandboxes/{sandbox_id}

Test cases:
  541 generated, 541 passed

=============================================== 1 warning in 33.89s ===============================================
```

## Écarts entre le code et le contrat, et ce qu'on a corrigé

### 1. Nom de fichier trop long : 500 au lieu de 400 (corrigé dans le code)

- Ce que Schemathesis a trouvé : `PUT /files?path=000…0` avec un nom de plus de 4000 caractères renvoyait 500 (code non documenté).
- Pourquoi : Linux refuse les noms de fichier de plus de 255 caractères, Docker renvoyait une erreur que le code ne gérait pas.
- Correction : `safe_path` refuse maintenant tout nom de fichier ou de dossier de plus de 255 caractères avec un 400 `invalid-path`. Le contrat ne change pas (400 était déjà prévu).

### 2. exit_code à null après un timeout (corrigé dans le code)

- `docker.exec_command` renvoie `exit_code: null` quand la commande est tuée par le timeout.
- Le contrat dit que `exit_code` est un entier, et 137 si la commande est tuée.
- Correction : dans execCommand, on remplace `null` par 137.

### 3. Paramètre path absent : 422 de FastAPI au lieu de 400 (corrigé dans le code)

- Par défaut, FastAPI renvoie 422 quand un paramètre obligatoire manque.
- Le contrat de readFile ne prévoit pas de 422, il prévoit 400 pour un chemin invalide.
- Correction : `path` est lu par notre code, et s'il manque on renvoie 400 `invalid-path`.

### 4. Warning sur le PATCH (pas corrigé, choix assumé)

- Schemathesis dit que le PATCH refuse la plupart des requêtes générées.
- Raison : il invente des identifiants `sbx-…` qui n'existent pas, donc l'API répond 404, et des If-Match au hasard, donc 412. C'est le comportement voulu.
- La phase Stateful, qui crée une vraie sandbox avant de la modifier, passe sans erreur.
