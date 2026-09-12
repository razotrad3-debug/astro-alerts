"""
Timeline X via syndication.twitter.com — l'endpoint public des embeds.

C'est ce que X sert aux sites qui affichent un fil embarque : pas de cle, pas
de compte. En echange il est limite par ADRESSE IP, et une IP trop sollicitee
recoit un 429 sec. Depuis une machine perso deja "vue" par X, il repond
souvent 429 ; depuis un runner GitHub Actions, souvent non. D'ou le mode
SOURCE_X=auto, qui essaie ici et retombe sur Telegram en cas d'echec.

Avantage decisif sur la chaine Telegram : le timeline est COMPLET. Le trader
ne relaie pas tout sur Telegram, et c'est exactement ce qui faisait manquer
des entrees.
"""
import json
import re

import requests

import config
from . import x_api

_TIMEOUT = 30
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_URL = "https://syndication.twitter.com/srv/timeline-profile/screen-name/{h}"
_RE_NEXT = re.compile(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


class ErreurSyndication(Exception):
    pass


def _entrees(page: str) -> list:
    """Extrait les tweets du JSON embarque dans la page."""
    m = _RE_NEXT.search(page)
    if not m:
        raise ErreurSyndication("Reponse sans __NEXT_DATA__ (format change ?).")
    try:
        donnees = json.loads(m.group(1))
    except Exception as e:
        raise ErreurSyndication("JSON illisible : " + str(e))

    fil = (donnees.get("props", {})
                  .get("pageProps", {})
                  .get("timeline", {}) or {})
    return fil.get("entries") or []


def _images(tweet: dict) -> list:
    """URLs des photos, en resolution d'origine."""
    urls = []
    for m in (tweet.get("mediaDetails") or tweet.get("photos") or []):
        if not isinstance(m, dict):
            continue
        if m.get("type") not in (None, "photo"):
            continue
        u = m.get("media_url_https") or m.get("url")
        if not u:
            continue
        base = u.split("?")[0]
        fmt = "jpg"
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            if base.lower().endswith(ext):
                fmt = "jpg" if ext == ".jpeg" else ext[1:]
                base = base[: -len(ext)]
                break
        # name=orig : la pleine resolution, indispensable pour lire un chart.
        urls.append(base + "?format=" + fmt + "&name=orig")
    return urls[:4]


def derniers_tweets(handle: str, brut_aussi: bool = False):
    """Le timeline complet du compte, au meme format que les autres sources."""
    try:
        r = requests.get(
            _URL.format(h=handle.lstrip("@")),
            params={"dsrc": "embed", "frame": "false", "lang": "en",
                    "showHeader": "false"},
            headers={"User-Agent": _UA, "Referer": "https://platform.twitter.com/"},
            timeout=_TIMEOUT,
        )
    except Exception as e:
        raise ErreurSyndication("syndication.twitter.com injoignable : " + str(e))

    if r.status_code == 429:
        raise ErreurSyndication(
            "syndication.twitter.com : 429, cette adresse IP est limitee par X."
        )
    if r.status_code == 404:
        raise ErreurSyndication("Compte introuvable : @" + handle)
    if r.status_code >= 400:
        raise ErreurSyndication("syndication a repondu " + str(r.status_code))

    entrees = _entrees(r.text)
    if not entrees:
        raise ErreurSyndication("Timeline vide (compte protege ou sans tweets ?).")

    bruts = []
    for e in entrees:
        t = (e.get("content") or {}).get("tweet")
        if not isinstance(t, dict):
            continue
        # On reconstruit la forme attendue par x_api.normaliser, pour que le
        # filtrage retweet/reponse se comporte comme sur les autres sources.
        bruts.append({
            "id_str": t.get("id_str") or t.get("conversation_id_str"),
            "full_text": t.get("full_text") or t.get("text") or "",
            "created_at": t.get("created_at") or "",
            "url": t.get("permalink") or (
                "https://x.com/" + handle + "/status/" + str(t.get("id_str"))),
            "in_reply_to_screen_name": t.get("in_reply_to_screen_name"),
            "retweeted_tweet": t.get("retweeted_status"),
            "_images": _images(t),
        })

    sortie = x_api.normaliser(bruts, handle)

    # normaliser() ne sait pas lire mediaDetails : on recolle les images.
    par_id = {str(b.get("id_str")): b.get("_images") or [] for b in bruts}
    for msg in sortie:
        msg["images"] = par_id.get(msg["id"], msg.get("images") or [])

    if brut_aussi:
        return sortie, r.text
    return sortie
