# x-short-watcher

Surveille un ou plusieurs comptes X, fait lire par Claude ce qu'ils publient —
le texte du tweet **et** les captures d'écran (charts TradingView, tickets
d'ordre, captures de PnL) — et envoie sur Telegram **ce qui a été shorté ou
longé, à quel prix**.

Calibré sur [@astronomer_zero](https://x.com/astronomer_zero).

```
tweet de @astronomer_zero  →  texte + images  →  Claude lit le setup
                 →  {ticker, sens, entrée, SL, TP, levier}  →  Telegram
```

---

## Installation

```bash
pip install -r requirements.txt
cp .env.example .env
```

Le projet tourne en **mode gratuit par défaut**. Il te reste deux clés à
créer, l'une et l'autre sans carte bancaire :

| Variable | Où | Gratuité |
|---|---|---|
| `APIFY_TOKEN` | [console.apify.com → Integrations](https://console.apify.com/settings/integrations) | 5 $ de crédits offerts **chaque mois** |
| `GEMINI_API_KEY` | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | **20 requêtes/jour et par modèle** — d'où la chaîne de 4 modèles, voir plus bas |

Telegram est déjà configuré (`@astro_short_watcher_bot`). Si tu repars de zéro,
voir plus bas.

### Créer le bot Telegram

1. Dans Telegram, cherche **@BotFather** → `/newbot` → donne un nom, puis un
   identifiant finissant par `bot`. Il te renvoie un token de la forme
   `123456789:AAF...` → colle-le dans `TELEGRAM_BOT_TOKEN`.
2. Cherche ton bot par son identifiant et envoie-lui `/start`. Ce premier
   message est obligatoire : un bot ne peut pas écrire à quelqu'un qui ne lui
   a jamais parlé.
3. Lance `python main.py --chatid` : il te sort la ligne
   `TELEGRAM_CHAT_ID=...` à recopier dans le `.env`.

Puis vérifie que tout répond :

```bash
python main.py --test
```

Ce diagnostic appelle twitterapi.io, affiche le dernier tweet et les images
détectées, le fait analyser par Claude, et t'envoie le résultat sur Telegram.
Si une brique est cassée, il te dit laquelle.

---

## Utilisation

```bash
python main.py                 # un passage (mode cron / GitHub Actions)
python main.py --boucle        # tourne en continu, un passage par minute
python main.py --rejouer 5     # re-analyse les 5 derniers tweets et envoie
python main.py --test          # diagnostic complet
```

Au **tout premier lancement**, le watcher note les tweets existants comme
« déjà vus » sans rien envoyer — sinon tu recevrais d'un coup les 20 derniers
tweets du compte. Pour tester sur du vrai contenu, utilise `--rejouer`.

---

## Déploiement sur GitHub Actions

Le workflow [`.github/workflows/watch.yml`](.github/workflows/watch.yml) fait
tourner le watcher toutes les 15 minutes et recommite `state.json` (la mémoire
du bot) après chaque passage.

1. Pousse ce dossier dans un repo GitHub.
2. **Settings → Secrets and variables → Actions → New repository secret**, un
   secret pour chacun : `X_HANDLES`, `TWITTERAPI_IO_KEY`, `ANTHROPIC_API_KEY`,
   `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
3. Onglet **Actions** → `x-short-watcher` → **Run workflow** pour le premier
   passage (celui-ci n'alertera pas, il initialise la mémoire).

### Le piège du `checkout` sur GitHub Actions

Constaté le 16/09/2026 : **la même alerte envoyée deux fois**, à 04h08 et
04h10, sur un seul et même post.

`actions/checkout` récupère par défaut `github.sha` — la tête de la branche
**au moment où l'événement a été créé**, pas au moment où le job démarre.
Comme les passages s'enchaînent toutes les 2 minutes et commitent leur
mémoire, un déclencheur parti à 02:08:17 portait le SHA d'avant le commit
d'état de 02:08:41. Le passage lisait donc un `state.json` sans le tweet,
le prenait pour nouveau, et alertait une seconde fois.

Deux parades, cumulées :

```yaml
- uses: actions/checkout@v4
  with:
    ref: ${{ github.event.repository.default_branch || 'main' }}
```

et, avant toute lecture, un rafraîchissement explicite de la mémoire depuis
la branche publiée (`git fetch` + `git show FETCH_HEAD:state.json`).

**Ce n'était pas un problème de concurrence.** Mesuré au niveau des *jobs* :
zéro recouvrement sur 20 transitions, les passages s'enchaînent à 2-4 s
d'intervalle — le bloc `concurrency` fait son travail. Les horodatages
`run_started_at` / `updated_at` de l'API donnent l'illusion de
chevauchements ; ce sont la création du run et sa dernière modification, pas
son exécution. Pour mesurer un vrai recouvrement, il faut les `started_at` /
`completed_at` **du job**.

### Trois limites à connaître

- **Latence : compte 15 à 30 min.** Le cron est réglé sur 15 min et GitHub
  le déclenche avec 5 à 15 min de retard supplémentaire aux heures chargées.
  Si la latence compte vraiment, un petit VPS avec `--boucle` descend à 60 s.
- **Minutes Actions : mets le repo en public.** Un repo public a des minutes
  illimitées. Sur un repo **privé** en plan gratuit tu n'as que 2 000 min/mois,
  et même un cron de 15 min en consomme ~2 900 — le quota saute. Le
  code ne contient aucun secret (ils vivent dans GitHub Secrets), donc public
  est sans risque ; garde juste `X_HANDLES` en *Secret* et non en *Variable*
  pour que le pseudo surveillé n'apparaisse pas en clair.
- **Les workflows planifiés sont désactivés après 60 jours** sans activité sur
  le repo. Un commit suffit à les relancer.

---

## Coût : 0 €

Rien à payer, rien à créer. Tout est déjà configuré et testé.

| Brique | Solution | Coût |
|---|---|---|
| Source | **sa chaîne Telegram publique** `t.me/AstronomerZero` | **0 €** — pas de clé, pas de compte, pas de quota |
| IA | **chaîne de 4 modèles Gemini** | **0 €** — ~80 analyses/jour, ~12 utilisées |
| Hébergement | GitHub Actions, repo public | **0 €** |

### Pourquoi passer par Telegram plutôt que par X

Il relaie ses tweets sur sa chaîne (9 400 abonnés), et Telegram y joint
l'aperçu du lien : **le texte du tweet et son image**, recopiée sur le CDN
Telegram. Or toute chaîne publique expose ses derniers messages en HTML brut
sur `https://t.me/s/<canal>` — une simple requête HTTP, sans authentification.

Bonus : on récupère aussi ses commentaires propres à la chaîne (« Entered
short on X live too », « Short working out too »), qui n'existent pas sur X.

**La limite** : Telegram tronque l'aperçu vers **190 caractères**, donc la fin
de ses longs posts est perdue. Le ticker, le sens et le prix clé sont
quasiment toujours dans les premières lignes, mais si tu veux le texte
intégral il faut `SOURCE_X=twitterapi` (~9 $/mois).

### Les deux autres sources, si un jour tu veux payer

```
SOURCE_X=twitterapi        # ~9 $/mois, texte complet, non tronqué
FOURNISSEUR_IA=anthropic   # ~6 $/mois, meilleur sur un chart chargé
```

**Apify ne marche pas gratuitement.** Le plan FREE n'a aucune session de
proxy résidentiel (`RESIDENTIAL: 0`, `UNBLOCKER: 0`), et X bloque les IP
datacenter. Mesuré le 12/09/2026 : trois acteurs, trois formats d'entrée,
tous en run « SUCCEEDED » avec zéro tweet
(`Fetched 0/5 tweets... No more tweets or cursor found`). Le code est gardé,
il redeviendra utile avec un plan Apify payant.

**Ton abonnement Claude ne remplace pas `ANTHROPIC_API_KEY`** : l'abonnement
couvre Claude Code et les applications, l'API est facturée séparément.

### Le quota Gemini est de 20/jour, pas 250

Mesuré sur l'API (`GenerateRequestsPerDayPerProjectPerModel-FreeTier = 20`),
pas dans la documentation. Mais il est compté **par modèle**, d'où la chaîne
de `GEMINI_MODELS` : quand le quota du jour d'un modèle est épuisé, le
suivant prend le relais automatiquement. Quatre modèles ≈ 80 analyses/jour.

Les 429 « par minute » (~10-15 req/min) sont distincts et réessayés
automatiquement avec attente.

### Protection du quota gratuit

Sa chaîne contient beaucoup de messages d'ambiance (« Well well well… »,
« A very good morning ») qui ne peuvent contenir aucun trade. Un pré-filtre
dans `main.py` les écarte **sans appeler l'IA** : mesuré, 7 messages évités
sur 19. Le filtre est volontairement large — au moindre chiffre, mot-clé ou
image, on analyse, car rater un setup coûte plus cher qu'un appel inutile.

---

## Ce que Gemini lit bien, et ce qu'il rate

Mesuré sur [ce post](https://x.com/astronomer_zero/status/2098413184638230533)
(texte + chart TradingView) :

**Bien lu** : ticker, sens short, entrée 79 300 depuis « 79.3k+ », objectif
76 000, timeframe 6h, exchange Coinbase, statut « ouverture », et un résumé
juste.

**Raté** : il a rapporté un `stop_loss` à 82 185, lu sur la boîte de position
du chart — qui décrit le trade **précédent**. Le tweet n'annonce aucun stop.

D'où le **contrôle de provenance** dans `watcher/vision.py` : chaque prix
extrait est recherché dans le texte du tweet, en tenant compte de la notation
`k` (79 300 ↔ « 79.3k »). Tout chiffre introuvable dans le texte est marqué
dans l'alerte — `⚠️ stop lu(s) sur le chart, absent(s) du tweet` — et la
confiance est rabaissée. Le chiffre reste affiché, parce qu'il est souvent
juste, mais il n'est jamais présenté comme une annonce du trader.

---

## Calibrage sur @astronomer_zero

Le prompt d'analyse est adapté à sa façon de poster, observée sur son fil :

- **Ses entrées sont souvent annoncées en texte, sans capture.** *« Flipped
  the longs, into shorts »*, *« we went short at 79.4k »*. Le texte du tweet
  est donc traité à égalité avec les images, pas comme un simple complément.
- **Notation en `k`.** `79.4k` est converti en `79400`. Sans cette règle, une
  alerte annoncerait une entrée à 79,4 $ sur du BTC.
- **Distinction niveau visé / position prise.** *« 76k is coming »* et *« c'est
  la zone où il faudra shorter »* ne sont pas des entrées : statut `analyse`,
  pas d'alerte. Il faut qu'il dise avoir la position.
- **Les flips.** *« Flipped the longs into shorts »* est à la fois une clôture
  et une ouverture : l'alerte décrit la nouvelle position et mentionne celle
  qui vient d'être fermée.
- **Beaucoup de bruit.** Une bonne moitié de ses posts est du commentaire de
  marché, des piques aux autres traders ou des annonces communautaires
  (*« Astro community - CPI print: 2 - 0 »*). Ils sont analysés puis écartés
  sans alerte.
- **Quasiment toujours $BTC**, ce qui rend le champ `ticker` facile.
- **Il poste en fils.** Le détail d'une entrée arrive souvent dans une suite,
  techniquement une réponse à lui-même. Le filtre `IGNORER_REPONSES` écarte
  donc les réponses **aux autres** mais garde ses self-threads.
- **Ses charts TradingView montrent souvent le trade *précédent*.** Vérifié sur
  [ce post](https://x.com/astronomer_zero/status/2098413184638230533) : le texte
  annonce un flip en short vers 79,3 k, pendant que l'image porte une boîte de
  position ancrée à 81 225 (SL 82 185, cible 75 788) couvrant le 4 au 12 sept —
  le short d'avant, déjà joué. Une lecture naïve aurait rapporté « entrée
  81 225 ». **En cas de désaccord texte/image, le texte fait foi**, les chiffres
  du chart partent dans `indices` signalés comme antérieurs, et la confiance
  descend d'un cran.

Pour suivre un autre compte, change `X_HANDLES` — le bot marchera, mais ces
réglages fins de prompt sont taillés pour lui. Les exemples concrets sont
dans `_SYSTEME`, en haut de [`watcher/vision.py`](watcher/vision.py).

### Où il place ses stops — et d'où sort le 0,9 %

Mesuré à la main sur ses graphiques, en relevant les étiquettes de prix que
TradingView pose sur l'axe pour chaque bord de l'outil de position. Onze
entrées datées entre le 23/07 et le 14/09/2026 :

| Date | Trade | Entrée | Stop | Distance |
|---|---|---|---|---|
| 02/08 | Short VI | 63 447,6 | 63 542,0 | 0,15 % |
| 02/09 | Long I (scalp) | 76 973,4 | 76 643,7 | 0,43 % |
| 27/07 | Short IV | 65 484,5 | 65 780,5 | 0,45 % |
| 30/07 | Long V | 63 447,6 | 63 103,6 | 0,54 % |
| 14/09 | Another short | 79 475,4 | 79 922,1 | 0,56 % |
| 11/09 | Short II | 79 475,4 | 80 053,6 | 0,73 % |
| 23/07 | Shorts III | 66 292,3 | 66 831,4 | 0,81 % |
| 12/08 | Short I compound | 65 254,5 | 65 790,1 | 0,82 % |
| 04/09 | Short II | 81 225,2 | 82 184,7 | 1,18 % |
| 28/08 | Short I (native) | 80 498,9 | 82 216,9 | 2,13 % |
| 21/08 | Long **positionnel** | 69 151,6 | 65 159,8 | **5,77 %** |

Sur les dix trades intraday et swing : **moyenne 0,78 %, médiane 0,65 %**,
soit environ 490 points sur du BTC à 80 k. Le onzième, un long journalier
tenu plusieurs semaines, n'appartient pas à la même famille — le mélanger
fait monter la moyenne à 1,24 % et ne veut plus rien dire.

**Le pourcentage n'est jamais sa décision.** Il pose son stop juste au-delà
d'un niveau qu'il a nommé — VAH, Weekly Open, weekly inst level, POC — et le
pourcentage tombe tout seul : 0,45 % quand la zone est étroite, 2,13 % quand
elle est large. C'est pour ça que le bot affiche toujours le stop **lu**
quand il est lisible, et ne calcule qu'à défaut.

Le repli est réglé à **0,9 %** (`STOP_ESTIME_PCT`) : c'est le point
d'inflexion de cette série — il couvre 8 des 10 trades, là où monter à
1,2 % en couvre un de plus pour un tiers de risque en plus.

**Vérification de la méthode de lecture.** Sur le short du 04/09, l'outil
donne entrée 81 225,16, stop 82 184,72, cible 79 295,40 — soit 2,01 RR. Dans
son texte du 05/09 il écrit *« 25 % locked in at 2.02 RR »*. Les chiffres
relevés au pixel retombent sur les siens.

---

## Ce que le bot fait et ne fait pas

**Il extrait** : ticker, sens (short/long), prix d'entrée, zone d'entrée, stop,
take-profits, levier, taille, exchange, timeframe, PnL affiché, et un statut
(ouverture / en cours / clôturé / simple analyse).

**Il ne devine pas.** La consigne donnée au modèle est explicite : si un prix
n'est pas lisible dans l'image ni écrit dans le texte, le champ est `null` et
**la ligne disparaît du message**. Pas de « non lisible », pas de `TP :` suivi
de rien — une ligne vide se lit comme une information, c'est pire que pas de
ligne. Un chiffre lu sur l'image seule, absent du texte, est marqué `(chart)` :
sur ce compte les boîtes de position décrivent souvent le trade précédent.

La confiance de lecture et la citation justificative sont extraites et
disponibles dans l'analyse, mais **plus affichées** : l'alerte a été réduite à
ce qui est actionnable d'un coup d'œil sur un téléphone, le lien `X` est là
pour le contexte.

C'est volontaire : un prix d'entrée halluciné serait pire que pas de prix,
parce que tu agirais dessus.

**Une seule exception, assumée : le stop.** Quand il n'est pas lisible, il
est déduit de l'entrée à 0,9 % (voir plus haut). L'alerte le marque alors
`~80 200 (est. 0,9 %)` — tilde et mention, jamais confondu avec un stop
annoncé, qui s'affiche lui sans tilde. Deux garde-fous avant affichage : un
stop du mauvais côté de l'entrée, ou à plus de 8 % d'elle, est écarté et
remplacé par l'estimation — c'est presque toujours une vieille boîte de
position restée sur le graphique. L'estimation ne se déclenche que sur les
statuts `ouverture` et `intention` : calculer un stop sous un post de suivi
laisserait croire qu'il y a encore une position à protéger.

**Il ne trade pas.** Ce bot lit et transmet, rien d'autre.

---

## Structure

| Fichier | Rôle |
|---|---|
| `config.py` | tous les réglages, lus depuis `.env` ou l'environnement |
| `watcher/x_telegram.py` | **source par défaut** : lecture de `t.me/s/<canal>` |
| `watcher/source.py` | aiguillage entre les trois sources |
| `watcher/x_api.py` | twitterapi.io (payant) |
| `watcher/x_apify.py` | Apify (inopérant sur le plan gratuit) |
| `watcher/vision.py` | analyse texte + images par Claude, sortie structurée |
| `watcher/message.py` | mise en forme du message Telegram |
| `watcher/telegram.py` | envoi (photo + légende, ou texte seul) |
| `watcher/etat.py` | mémoire des tweets déjà traités (`state.json`) |
| `main.py` | orchestration et ligne de commande |

### Si twitterapi.io change son format

`watcher/x_api.py` cherche les tweets et les images à plusieurs emplacements
possibles dans le JSON, et en dernier recours pêche les URLs `pbs.twimg.com`
directement dans la réponse brute. Si malgré tout `--test` ne détecte aucun
tweet, il affiche les clés du JSON reçu : ajuste alors `TWITTERAPI_IO_PATH`
dans le `.env`, sans toucher au code.
