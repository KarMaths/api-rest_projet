# TP4 : client robuste

Binôme : Karl JEAN / Anas Louraibi. Mesures faites avec `make flaky` et `bash mesures_tp4.sh`.

## Le constat de départ (client naïf du squelette)

| Mesure | Résultat | Problème |
|---|---|---|
| `sbx ls \| wc -l` | 20 (sur 511) | seule la première page est lue |
| 20 fois `sbx create` | 14 succès sur 20 | les 429, 503 et réponses lentes font échouer la commande |
| sandboxes en plus dans `/_stats` | +24 (511 → 535) | plus de sandboxes que de succès : des réponses perdues (502) ont quand même créé une sandbox, sans que le client le sache |

## Ce qu'on a changé dans `client/sbx.py`

- **Timeouts** sur chaque appel (5 s de connexion, 70 s de lecture pour les exec longs).
- **Nouveaux essais** seulement pour 429, 502, 503, 504 et les erreurs réseau. Jamais pour 400, 404 ou 422.
- **Attente** : `Retry-After` s'il est présent, sinon backoff exponentiel avec du hasard (full jitter, 8 s au plus).
- **Abandon** après 6 essais, avec un message clair et un code de sortie 1.
- **Création rejouable** : une `Idempotency-Key` par création, réutilisée à chaque nouvel essai. Un POST sans clé n'est jamais rejoué.
- **Pagination** : `sbx ls` suit `next_page_token` jusqu'au bout.
- **`create --wait`** interroge l'adresse de `Location` jusqu'à `ready` ou `failed`.
- **`exec`** affiche stdout et stderr séparément et sort avec le code de la commande.
- **`rm`** accepte un 404 (DELETE est idempotent).
- Un seul `httpx.Client` par commande.

## Les mêmes mesures avec notre client

| Mesure | Avant | Après |
|---|---|---|
| `sbx ls \| wc -l` | 20 | **535** (toutes, 0 doublon) |
| 20 fois `sbx create` | 14 / 20 | **20 / 20** |
| sandboxes en plus dans `/_stats` | +24 | **+20 exactement** (535 → 555) |
| réponses perdues pendant les créations | — | 3, rattrapées par l'Idempotency-Key (`idempotent_replays` 5 → 8) |
| `sbx create --wait` | — | affiche l'id une fois la sandbox ready |
| `sbx rm` deux fois | — | code 0 les deux fois |

Le même client fonctionne contre notre sandboxd (`SANDBOXD_URL=http://localhost:8000`, avec `SANDBOXD_API_KEY`).
