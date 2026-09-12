"""Choisit la source des tweets selon SOURCE_X, et expose une seule fonction."""
import config
from . import x_api, x_apify, x_syndication, x_telegram


class ErreurSource(Exception):
    pass


# Quelle source a reellement repondu au dernier appel (le mode auto peut
# basculer). La memoire des tweets vus en depend.
_DERNIERE = "?"


def derniere_source() -> str:
    return _DERNIERE


def nom() -> str:
    if config.SOURCE_X == "auto":
        return "auto (X syndication, repli Telegram)"
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
        try:
            r = x_syndication.derniers_tweets(handle, brut_aussi)
            _DERNIERE = "x"
            return r
        except x_syndication.ErreurSyndication as e:
            print("[source] X indisponible (" + str(e)[:80]
                  + ") -> repli sur la chaine Telegram")
        try:
            r = x_telegram.derniers_tweets(config.TELEGRAM_CANAL, brut_aussi)
            _DERNIERE = "telegram"
            return r
        except x_telegram.ErreurTelegram as e:
            raise ErreurSource(str(e))

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
