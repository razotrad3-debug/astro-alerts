"""Choisit la source des tweets selon SOURCE_X, et expose une seule fonction."""
import time

import config
from . import x_api, x_apify, x_syndication, x_telegram


class ErreurSource(Exception):
    pass


# Quelle source a reellement repondu au dernier appel (le mode auto peut
# basculer). La memoire des tweets vus en depend.
_DERNIERE = "?"


def derniere_source() -> str:
    return _DERNIERE


def _fusionner(*listes):
    """Reunit plusieurs sources en dedoublonnant sur l'identifiant.

    La premiere liste est prioritaire : quand X et Telegram voient le meme
    post, on garde la version X (texte complet, image d'origine) et on
    ignore l'apercu Telegram, plus pauvre.
    """
    vus = {}
    for liste in listes:
        for msg in liste or []:
            if msg["id"] not in vus:
                vus[msg["id"]] = msg

    def _cle(m):
        try:
            return (1, int(str(m["id"]).replace("tg-", "")))
        except Exception:
            return (0, 0)
    return sorted(vus.values(), key=_cle)


def nom() -> str:
    if config.SOURCE_X == "auto":
        return "X + Apify + Telegram (fusionnes)"
    if config.SOURCE_X == "syndication":
        return "X syndication"
    if config.SOURCE_X == "telegram":
        return "Telegram t.me/" + config.TELEGRAM_CANAL
    if config.SOURCE_X == "apify":
        return "Apify"
    return "twitterapi.io"


def derniers_tweets(handle: str, brut_aussi: bool = False):
    """Les derniers tweets du compte, quelle que soit la source configuree.

    Les deux sources renvoient exactement le meme format (x_api.normaliser),
    donc tout le reste du programme ignore laquelle est active.
    """
    # Mode auto : le timeline X est complet, la chaine Telegram ne l'est pas.
    # On prefere donc X, et on ne bascule que s'il refuse (429 selon l'IP).
    global _DERNIERE
    if config.SOURCE_X == "auto":
        # On interroge les DEUX et on fusionne : X est plus complet mais
        # refuse par intermittence, Telegram est partiel mais toujours la.
        # Leur reunion est plus sure que l'un ou l'autre seul.
        depuis_x = depuis_tg = depuis_apify = []
        sources = []

        # Gratuit et illimite, mais refuse souvent (429 selon l'IP).
        try:
            depuis_x = x_syndication.derniers_tweets(handle)
            sources.append("x(" + str(len(depuis_x)) + ")")
        except x_syndication.ErreurSyndication as e:
            print("[source] X indisponible : " + str(e)[:90])

        # Gratuit et toujours disponible, mais il n'y relaie pas tout.
        try:
            depuis_tg = x_telegram.derniers_tweets(config.TELEGRAM_CANAL)
            sources.append("telegram(" + str(len(depuis_tg)) + ")")
        except x_telegram.ErreurTelegram as e:
            print("[source] Telegram indisponible : " + str(e)[:90])

        # Apify voit tout mais chaque tweet ramene est facture : on ne
        # l'appelle qu'a intervalle espace, pour tenir dans les credits
        # offerts. Il sert de filet sur ce que les deux autres ont manque.
        if config.APIFY_TOKEN:
            from . import etat
            ecoule = (time.time() - etat.horodatage("apify")) / 60.0
            if ecoule >= config.APIFY_INTERVALLE_MIN:
                try:
                    depuis_apify = x_apify.derniers_tweets(handle)
                    etat.poser_horodatage("apify")
                    sources.append("apify(" + str(len(depuis_apify)) + ")")
                except x_apify.ErreurApify as e:
                    print("[source] Apify indisponible : " + str(e)[:90])
            else:
                print("[source] Apify dans " + str(int(config.APIFY_INTERVALLE_MIN - ecoule))
                      + " min (credits menages)")

        if not depuis_x and not depuis_tg and not depuis_apify:
            raise ErreurSource("aucune source disponible")

        _DERNIERE = "+".join(sources) or "aucune"
        # Ordre de priorite : X, puis Apify, puis l'apercu Telegram, plus pauvre.
        fusion = _fusionner(depuis_x, depuis_apify, depuis_tg)
        if brut_aussi:
            return fusion, {}
        return fusion

    try:
        if config.SOURCE_X == "syndication":
            _DERNIERE = "x"
            return x_syndication.derniers_tweets(handle, brut_aussi)
        if config.SOURCE_X == "telegram":
            _DERNIERE = "telegram"
            return x_telegram.derniers_tweets(config.TELEGRAM_CANAL, brut_aussi)
        if config.SOURCE_X == "apify":
            _DERNIERE = "apify"
            return x_apify.derniers_tweets(handle, brut_aussi)
        if config.SOURCE_X in ("twitterapi", "twitterapi.io", "twitter"):
            _DERNIERE = "twitterapi"
            return x_api.derniers_tweets(handle, brut_aussi)
    except (x_syndication.ErreurSyndication, x_telegram.ErreurTelegram,
            x_apify.ErreurApify, x_api.ErreurX) as e:
        raise ErreurSource(str(e))

    raise ErreurSource(
        "SOURCE_X inconnu : " + str(config.SOURCE_X)
        + " (attendu : auto, syndication, telegram, twitterapi ou apify)"
    )
