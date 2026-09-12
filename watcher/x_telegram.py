"""
Lecture de la chaine Telegram publique du trader — la source gratuite.

Toute chaine Telegram publique expose ses derniers messages en HTML brut sur
https://t.me/s/<canal>. Pas de cle, pas de compte, pas de quota : une simple
requete HTTP. Comme @astronomer_zero relaie ses tweets sur sa chaine, on y
retrouve le lien du tweet, son texte, et son image recopiee sur le CDN
Telegram (donc telechargeable sans se battre contre X).

Limite connue et assumee : Telegram tronque le texte de l'apercu vers 190
caracteres. On perd la fin des longs posts. En echange, c'est gratuit et ca
ne peut pas etre bloque comme un scraper.
"""
import re

import requests
from bs4 import BeautifulSoup

import config

_TIMEOUT = 30
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

_RE_STATUT = re.compile(r"https?://(?:x|twitter)\.com/([A-Za-z0-9_]+)/status/(\d+)")
_RE_FOND = re.compile(r"background-image\s*:\s*url\(['\"]?([^'\")]+)")


class ErreurTelegram(Exception):
    pass


def _fond(balise) -> str:
    """URL d'image cachee dans un style inline background-image."""
    if balise is None:
        return ""
    m = _RE_FOND.search(balise.get("style", "") or "")
    return m.group(1) if m else ""


def _texte_de(balise) -> str:
    """Texte d'un bloc, avec les <br> rendus en vrais sauts de ligne."""
    if balise is None:
        return ""
    for br in balise.find_all("br"):
        br.replace_with("\n")
    return balise.get_text().strip()


def _message(bloc, canal: str) -> dict:
    """Transforme un message de la page en tweet normalise, ou None."""
    poste = bloc.get("data-post") or ""
    num = poste.split("/")[-1] if "/" in poste else ""
    if not num:
        return None

    corps = _texte_de(bloc.select_one(".tgme_widget_message_text"))

    # L'apercu du lien porte le vrai contenu quand le message n'est qu'une URL.
    apercu = bloc.select_one(".tgme_widget_message_link_preview")
    titre = description = ""
    images = []
    if apercu is not None:
        titre = _texte_de(apercu.select_one(".link_preview_title"))
        description = _texte_de(apercu.select_one(".link_preview_description"))
        for sel in (".link_preview_image", ".link_preview_right_image"):
            u = _fond(apercu.select_one(sel))
            if u and u not in images:
                images.append(u)

    # Photos postees directement dans la chaine.
    for photo in bloc.select(".tgme_widget_message_photo_wrap"):
        u = _fond(photo)
        if u and u not in images:
            images.append(u)

    # Le lien du tweet donne l'URL de reference ; sinon on pointe le message.
    lien_x = ""
    for a in bloc.find_all("a", href=True):
        if _RE_STATUT.search(a["href"]):
            lien_x = a["href"].split("?")[0]
            break
    if not lien_x:
        m = _RE_STATUT.search(str(bloc))
        if m:
            lien_x = m.group(0)

    # On assemble ce qu'on a : le corps du message (son commentaire perso),
    # le titre de l'apercu (premiere ligne du tweet) et sa description.
    morceaux = []
    corps_sans_url = _RE_STATUT.sub("", corps).strip()
    if corps_sans_url:
        morceaux.append(corps_sans_url)
    if description:
        morceaux.append(description)
    elif titre:
        morceaux.append(titre)
    texte = "\n\n".join(morceaux).strip()

    if not texte and not images:
        return None

    date = ""
    t = bloc.select_one("time")
    if t is not None:
        date = t.get("datetime", "") or ""

    return {
        # Prefixe tg- : l'identifiant est celui du message Telegram, pas du
        # tweet. Deux messages peuvent pointer le meme tweet (relais + suite).
        "id": "tg-" + num,
        "handle": config.HANDLES[0] if config.HANDLES else canal,
        "texte": texte,
        "images": images[:4],
        "url": lien_x or ("https://t.me/" + canal + "/" + num),
        "date": date,
        "tronque": bool(description),  # l'apercu Telegram coupe vers 190 car.
    }


_FX = "https://api.fxtwitter.com/i/status/{id}"


def _enrichir(msg: dict) -> dict:
    """Remplace l'apercu Telegram par le vrai contenu du tweet.

    Telegram tronque le texte vers 190 caracteres et redimensionne l'image en
    800px. fxtwitter est un miroir public et gratuit qui rend le texte entier
    et l'image d'origine (2710x1474 sur l'exemple teste) — indispensable pour
    lire les petits chiffres d'un graphique.

    En cas d'echec on garde la version Telegram : degrade, mais jamais vide.
    """
    m = _RE_STATUT.search(msg.get("url") or "")
    if not m:
        return msg

    try:
        r = requests.get(_FX.format(id=m.group(2)),
                         headers={"User-Agent": _UA}, timeout=20)
        if r.status_code != 200:
            return msg
        tweet = (r.json() or {}).get("tweet") or {}
    except Exception:
        return msg

    texte = (tweet.get("text") or "").strip()
    if len(texte) > len(msg.get("texte") or ""):
        # On garde devant le commentaire que le trader a ajoute sur Telegram :
        # il n'existe pas sur X et porte souvent l'intention ("Entered short").
        propre = (msg.get("texte") or "").split("\n\n")[0].strip()
        ancien_debut = propre and not propre.startswith(("http", "$"))
        msg["texte"] = (propre + "\n\n" + texte) if ancien_debut else texte
        msg["tronque"] = False

    medias = (tweet.get("media") or {}).get("photos") or []
    urls = []
    for p in medias:
        u = p.get("url")
        if u:
            # ?name=orig force la resolution d'origine plutot qu'une vignette.
            urls.append(u if "name=" in u else u + "?name=orig")
    # fxtwitter fait autorite sur les medias : s'il n'en signale aucun, le
    # tweet n'a pas d'image et ce que Telegram montrait etait une vignette
    # de profil. La vider evite de la prendre pour un graphique — et, avec
    # ANALYSER_SANS_IMAGE=false, evite une analyse inutile.
    msg["images"] = urls[:4]

    return msg


def derniers_tweets(canal: str, brut_aussi: bool = False, avant=None):
    """Les derniers messages de la chaine, au meme format que les autres sources.

    `avant` remonte dans l'historique : t.me/s/<canal>?before=<id> rend les
    20 messages precedant cet identifiant. Sert au rattrapage manuel, pas au
    fonctionnement normal.
    """
    url = "https://t.me/s/" + canal.lstrip("@")
    params = {"before": str(avant)} if avant else None
    try:
        r = requests.get(url, params=params, headers={"User-Agent": _UA},
                         timeout=_TIMEOUT)
    except Exception as e:
        raise ErreurTelegram("Telegram injoignable : " + str(e))

    if r.status_code == 404:
        raise ErreurTelegram(
            "Chaine introuvable : " + canal + ". Verifie TELEGRAM_CANAL "
            "(le nom apres t.me/, la chaine doit etre publique)."
        )
    if r.status_code >= 400:
        raise ErreurTelegram("t.me a repondu " + str(r.status_code))

    soupe = BeautifulSoup(r.text, "html.parser")
    blocs = soupe.select(".tgme_widget_message[data-post]")
    if not blocs:
        raise ErreurTelegram(
            "Aucun message lu sur " + url + ". La chaine est peut-etre privee, "
            "ou Telegram a change sa mise en page."
        )

    sortie = []
    for bloc in blocs:
        msg = _message(bloc, canal.lstrip("@"))
        if msg:
            sortie.append(_enrichir(msg))

    # t.me/s/ rend deja du plus ancien au plus recent, mais on ne s'y fie pas.
    def _cle(x):
        try:
            return int(x["id"].split("-")[-1])
        except Exception:
            return 0
    sortie.sort(key=_cle)

    if brut_aussi:
        return sortie, r.text
    return sortie
