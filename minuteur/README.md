# Minuteur Cloudflare

Réveille le watcher plus vite que le cron GitHub. **5 minutes à installer,
aucune ligne de commande, aucune carte bancaire.**

## Pourquoi

Mesuré sur ce repo : le cron est réglé sur 5 minutes, mais GitHub ne
déclenche en réalité que toutes les **15 à 19 minutes** — il bride les
workflows planifiés fréquents. En revanche, les déclenchements par
*événement* ne sont pas bridés et partent en quelques secondes.

Ce Worker poste un événement `verifier` sur le repo. C'est tout — il ne fait
aucun travail lui-même.

## 1. Créer le jeton GitHub

[github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new)

| Champ | Valeur |
|---|---|
| Token name | `minuteur-astro-alerts` |
| Expiration | 1 an |
| Repository access | **Only select repositories** → `astro-alerts` |
| Permissions → Repository → **Contents** | **Read and write** |

Ne donne rien d'autre. Ainsi, même si le jeton fuitait, il ne permettrait
d'agir que sur ce seul repo.

Copie le jeton (`github_pat_...`) — il ne sera plus affiché ensuite.

## 2. Créer le Worker

[dash.cloudflare.com](https://dash.cloudflare.com) → **Compute (Workers)** →
**Create** → **Start from Hello World** → nomme-le `astro-minuteur` → Deploy.

Puis **Edit code**, remplace tout par le contenu de [`worker.js`](worker.js),
et redéploie.

## 3. Les deux secrets

Dans le Worker → **Settings** → **Variables and Secrets** → Add :

| Nom | Type | Valeur |
|---|---|---|
| `GITHUB_TOKEN` | Secret | le jeton de l'étape 1 |
| `GITHUB_REPO` | Text | `razotrad3-debug/astro-alerts` |

## 4. Le déclencheur

Worker → **Settings** → **Triggers** → **Cron Triggers** → Add :

```
*/2 * * * *
```

Toutes les 2 minutes. Cloudflare accepte la minute (`* * * * *`), mais
2 minutes suffisent : le compteur qui détecte un nouveau tweet met de toute
façon quelques dizaines de secondes à se rafraîchir. Et cela divise par deux
le nombre de passages GitHub — voir la réserve plus bas.

## 5. Vérifier

Ouvre l'URL du Worker (`https://astro-minuteur.<ton-compte>.workers.dev`)
dans un navigateur. Elle doit afficher :

```
Signal envoye au watcher.
```

Puis va dans l'onglet **Actions** du repo : un passage doit démarrer dans les
secondes qui suivent, avec l'événement `repository_dispatch`.

## Ce que ça donne

| | Avant | Après |
|---|---|---|
| Déclenchement | toutes les 15-19 min | toutes les 2 min |
| Latence totale | 15-20 min | **1 à 3 min** |
| Coût | 0 € | 0 € |

Le cron GitHub reste en place : si le Worker tombe, le watcher continue de
tourner, simplement plus lentement.

## Une réserve à connaître

Un passage toutes les 2 minutes fait ~720 exécutions par jour. Les minutes
Actions sont illimitées sur un repo public, donc ce n'est pas une question
de quota — mais GitHub Actions est prévu pour de l'intégration continue, pas
pour du sondage permanent. Si ton repo venait à être bridé, espace le cron
Cloudflare (`*/5`) ; la latence remonterait à 5-6 min, ce qui resterait bien
meilleur que les 15-19 min actuelles.
