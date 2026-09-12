"""
Recuperation des tweets via twitterapi.io.

Le format exact de la reponse peut evoluer (c'est une API non officielle).
On extrait donc les champs de facon defensive : on essaie plusieurs chemins
connus, et en dernier recours on peche les URLs d'images directement dans le
JSON brut. Mieux vaut un champ manquant qu'un plantage a 3h du matin.
"""
import json
import re
import requests

import config

_TIMEOUT = 25

# Les images de X vivent toutes sur ce domaine. Filet de securite quand la
# structure du JSON ne correspond a aucun chemin connu.
_RE_MEDIA = re.compile(r"https://pbs\.twimg\.com/media/[A-Za-z0-9_\-]+(?:\.(?:jpg|jpeg|png|webp))?(?:\?[^\"'\ ]*)?")


class ErreurX(Exception):
    pass


def _get(chemin: str, params: dict) -> dict:
    url = f"{config.TWITTERAPI_BASE}{chemin}"
    r = requests.get(
        url,
        params=params,
        headers={"X-API-Key": config.TWITTERAPI_KEY, "Accept": "application/json"},
        timeout=_TIMEOUT,
    )
    if r.status_code == 401 or r.status_code == 403:
        raise ErreurX(f"Cle twitterapi.io refusee ({r.status_code}). Verifie TWITTERAPI_IO_KEY.")
    if r.status_code == 402:
        raise ErreurX("twitterapi.io : credits epuises (402). Recharge le compte.")
    if r.status_code == 429:
        raise ErreurX("twitterapi.io : trop de requetes (429). Espace les appels.")
    if r.status_code >= 400:
        raise ErreurX(f"twitterapi.io a repondu {r.status_code} : {r.text[:300]}")
    try:
        return r.json()
    except Exception:
        raise ErreurX(f"Reponse illisible de twitterapi.io : {r.text[:300]}")


def _liste_tweets(brut: dict) -> list:
    """Trouve le tableau de tweets, quel que soit son emplacement."""
    if isinstance(brut, list):
        return brut
    for cle in ("tweets", "data", "results", "items"):
        val = brut.get(cle)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            for sous in ("tweets", "data", "results", "items"):
                if isinstance(val.get(sous), list):
                    return val[sous]
    return []


def _images(tweet: dict) -> list:
    """URLs des images du tweet, en haute definition, sans doublons."""
    trouvees = []

    def _ajouter(u):
        if not u or not isinstance(u, str):
            return
        if "pbs.twimg.com" not in u and "video.twimg.com" not in u:
            return
        # X sert par defaut une vignette, trop floue pour lire un prix sur un
        # chart. La forme canonique pour la haute definition est
        # <url sans extension>?format=<ext>&name=large.
        base = u.split("?")[0]
        fmt = "jpg"
        for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            if base.lower().endswith(ext):
                fmt = "jpg" if ext == ".jpeg" else ext[1:]
                base = base[: -len(ext)]
                break
        if base not in [t.split("?")[0] for t in trouvees]:
            trouvees.append(base + "?format=" + fmt + "&name=large")

    conteneurs = []
    for cle in ("extendedEntities", "extended_entities", "entities"):
        bloc = tweet.get(cle)
        if isinstance(bloc, dict) and isinstance(bloc.get("media"), list):
            conteneurs.append(bloc["media"])
    if isinstance(tweet.get("media"), list):
        conteneurs.append(tweet["media"])

    for media in conteneurs:
        for m in media:
            if not isinstance(m, dict):
                continue
            # On ne garde que les photos : une video ne se lit pas en une image.
            if m.get("type") not in (None, "photo", "image"):
                continue
            for champ in ("media_url_https", "media_url", "url", "expanded_url"):
                _ajouter(m.get(champ))

    if not trouvees:
        # Filet : le JSON a une forme qu'on ne connait pas encore.
        for u in _RE_MEDIA.findall(json.dumps(tweet)):
            _ajouter(u)

    return trouvees[:4]  # X plafonne a 4 images par tweet


def _texte(tweet: dict) -> str:
    """Le texte le plus complet disponible.

    On prend le plus LONG des champs candidats, pas le premier : certaines
    reponses contiennent a la fois un "text" tronque a 140 caracteres et un
    "full_text" entier. Or c'est justement la fin des longs posts qui porte
    le detail de l'entree, donc une troncature perdrait l'essentiel.
    """
    candidats = []
    for cle in ("full_text", "fullText", "text", "content", "legacy_full_text"):
        v = tweet.get(cle)
        if isinstance(v, str) and v.strip():
            candidats.append(v.strip())
    return max(candidats, key=len) if candidats else ""


def _id(tweet: dict) -> str:
    for cle in ("id", "id_str", "tweet_id", "rest_id"):
        v = tweet.get(cle)
        if v:
            return str(v)
    return ""


def _est_reponse(tweet: dict, handle: str = "") -> bool:
    """Vrai seulement pour une reponse a QUELQU'UN D'AUTRE.

    Ce trader poste ses analyses en fils : le detail d'une entree arrive
    souvent dans une suite, qui est techniquement une reponse a lui-meme.
    Les ecarter ferait rater l'essentiel, donc un self-thread n'est jamais
    traite comme une reponse.
    """
    h = (handle or "").lower().lstrip("@")

    # Reponse a soi-meme : on garde, c'est une suite de fil.
    for cle in ("inReplyToUsername", "in_reply_to_screen_name",
                "inReplyToScreenName", "replyToUsername"):
        cible = tweet.get(cle)
        if isinstance(cible, str) and cible:
            return cible.lower().lstrip("@") != h

    # Meme logique sur l'identifiant numerique quand le pseudo n'est pas donne.
    auteur = tweet.get("author") if isinstance(tweet.get("author"), dict) else {}
    mon_id = str(auteur.get("id") or tweet.get("userId") or tweet.get("user_id") or "")
    for cle in ("inReplyToUserId", "in_reply_to_user_id"):
        cible = tweet.get(cle)
        if cible:
            return not (mon_id and str(cible) == mon_id)

    texte = _texte(tweet)
    if texte.startswith("@"):
        premier = texte.split()[0].lstrip("@").rstrip(":,").lower()
        return premier != h

    # Un marqueur de reponse sans cible identifiable : on ne peut pas trancher,
    # donc on garde. Une alerte en trop vaut mieux qu'un setup manque.
    return False


def _est_retweet(tweet: dict) -> bool:
    if tweet.get("retweeted_tweet") or tweet.get("retweetedTweet"):
        return True
    if tweet.get("isRetweet") or tweet.get("is_retweet"):
        return True
    return _texte(tweet).startswith("RT @")


def _url(tweet: dict, handle: str) -> str:
    u = tweet.get("url") or tweet.get("twitterUrl") or tweet.get("tweetUrl")
    if isinstance(u, str) and u.startswith("http"):
        return u
    tid = _id(tweet)
    return f"https://x.com/{handle}/status/{tid}" if tid else f"https://x.com/{handle}"


def normaliser(bruts, handle: str) -> list:
    """Transforme des tweets bruts en dicts propres, du plus ancien au plus recent.

    Partage entre twitterapi.io et Apify : les deux renvoient des objets de
    forme proche (heritee de l'API X), et tout le filtrage retweet/reponse
    doit se comporter pareil quelle que soit la source.
    """
    sortie = []
    for t in bruts:
        if not isinstance(t, dict):
            continue
        tid = _id(t)
        if not tid:
            continue
        if config.IGNORER_RETWEETS and _est_retweet(t):
            continue
        if config.IGNORER_REPONSES and _est_reponse(t, handle):
            continue
        sortie.append({
            "id": tid,
            "handle": handle,
            "texte": _texte(t),
            "images": _images(t),
            "url": _url(t, handle),
            "date": t.get("createdAt") or t.get("created_at") or "",
        })

    # Snowflake : l'id croit avec le temps, on trie dessus quand il est numerique.
    def _cle(x):
        try:
            return int(x["id"])
        except Exception:
            return 0
    sortie.sort(key=_cle)
    return sortie


def derniers_tweets(handle: str, brut_aussi: bool = False):
    """Les derniers tweets d'un compte via twitterapi.io."""
    donnees = _get(config.TWITTERAPI_PATH, {"userName": handle})
    sortie = normaliser(_liste_tweets(donnees), handle)
    if brut_aussi:
        return sortie, donnees
    return sortie
