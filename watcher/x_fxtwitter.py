"""
Timeline X via fxtwitter — api.fxtwitter.com/2/profile/<compte>/statuses.

Source principale depuis le 25/09/2026. Ce jour-la, les trois sources
precedentes etaient mortes en meme temps, et le bot tournait a vide depuis
le 22/09 sans le savoir :
  - syndication.twitter.com repondait 429 aux machines GitHub comme au PC ;
  - la chaine Telegram AstronomerZero ne relayait plus rien depuis le 15/09 ;
  - Apify refusait (402, credits epuises).

fxtwitter sert la timeline complete, gratuitement, sans cle, avec le texte
entier, les photos en pleine resolution, et signale les reposts et les
reponses. C'est le meme service qui nous donnait deja le compteur de tweets.
"""
import re

import requests

import config

_TIMEOUT = 20
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_URL = "https://api.fxtwitter.com/2/profile/{h}/statuses"
_RE_MEDIA = re.compile(r"(https://pbs\.twimg\.com/media/[A-Za-z0-9_\-]+)")


class ErreurFxtwitter(Exception):
    pass


def _images(statut: dict) -> list:
    """Photos en resolution d'origine, indispensable pour lire un chart."""
    media = statut.get("media") or {}
    photos = media.get("photos") or [m for m in (media.get("all") or [])
                                     if m.get("type") == "photo"]
    urls = []
    for p in photos:
        m = _RE_MEDIA.search(str(p.get("url") or ""))
        if m:
            urls.append(m.group(1) + "?format=jpg&name=orig")
    return urls[:4]


def _texte(statut: dict) -> str:
    """Le plus long des champs texte : l'un des deux est parfois tronque."""
    brut = statut.get("raw_text")
    candidats = [statut.get("text") or "",
                 (brut.get("text") if isinstance(brut, dict) else brut) or ""]
    return max(candidats, key=len)


def _reponse_a_autrui(statut: dict, handle: str) -> bool:
    """Reponse a un autre compte ? Ses fils (reponses a lui-meme) restent."""
    cible = statut.get("replying_to")
    if not cible:
        return False
    nom = cible.get("screen_name") if isinstance(cible, dict) else str(cible)
    return (nom or "").lower().lstrip("@") != handle.lower().lstrip("@")


def derniers_tweets(handle: str) -> list:
    """Les derniers posts du compte, au format commun des sources."""
    try:
        r = requests.get(_URL.format(h=handle.lstrip("@")),
                         headers={"User-Agent": _UA}, timeout=_TIMEOUT)
    except Exception as e:
        raise ErreurFxtwitter("api.fxtwitter.com injoignable : " + str(e))
    if r.status_code != 200:
        raise ErreurFxtwitter("api.fxtwitter.com a repondu " + str(r.status_code))
    try:
        resultats = r.json().get("results") or []
    except Exception:
        raise ErreurFxtwitter("reponse fxtwitter illisible")
    if not resultats:
        raise ErreurFxtwitter("timeline vide")

    sortie = []
    for s in resultats:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        # Un repost n'est pas un post de lui : meme regle que les autres sources.
        if s.get("reposted_by") and config.IGNORER_RETWEETS:
            continue
        if config.IGNORER_REPONSES and _reponse_a_autrui(s, handle):
            continue
        sortie.append({
            "id": str(s["id"]),
            "handle": handle,
            "texte": _texte(s),
            "images": _images(s),
            "url": s.get("url") or ("https://x.com/" + handle + "/status/" + str(s["id"])),
            "date": s.get("created_at") or "",
            "tronque": False,
        })
    return sortie
