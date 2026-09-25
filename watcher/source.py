"""Choisit la source des tweets selon SOURCE_X, et expose une seule fonction."""
import time

import config
from . import etat, x_api, x_apify, x_fxtwitter, x_syndication, x_telegram


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
    vus, signatures = {}, set()
    for liste in listes:
        for msg in liste or []:
            if msg["id"] in vus:
                continue
            # Deuxieme cle : le contenu. L'identifiant ne suffit pas quand
            # Telegram relaie un tweet sans lien /status/ — il recoit alors
            # un "tg-<num>" qui ne correspondra jamais au numero de tweet
            # vu sur X, et le meme post passait deux fois.
            sig = etat.empreinte(msg)
            if sig and sig in signatures:
                continue
            if sig:
                signatures.add(sig)
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


def complement_apify(handle: str):
    """Interroge Apify, en garantissant un espacement minimal.

    Facture au tweet ramene : on ne vient ici que lorsque le compteur
    gratuit a bouge et que ni X ni Telegram n'ont rapporte le post. Le
    garde-fou d'espacement evite qu'un bug de detection ne vide les
    credits en une nuit.
    """
    global _DERNIERE
    if not config.APIFY_TOKEN:
        return []
    from . import etat
    ecoule = (time.time() - etat.horodatage("apify")) / 60.0
    if ecoule < config.APIFY_MIN_ENTRE_APPELS:
        print("[source] Apify appele il y a " + str(int(ecoule))
              + " min, on attend (garde-fou credits)")
        return []
    try:
        lot = x_apify.derniers_tweets(handle)
    except x_apify.ErreurApify as e:
        print("[source] Apify indisponible : " + str(e)[:90])
        return []
    etat.poser_horodatage("apify")
    _DERNIERE = (_DERNIERE + "+apify(" + str(len(lot)) + ")").lstrip("+")
    return lot


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
        depuis_fx = depuis_x = depuis_tg = depuis_apify = []
        sources = []

        # Source principale depuis le 25/09/2026 : timeline complete, gratuite,
        # et elle repond la ou X renvoie 429. Voir x_fxtwitter.py.
        try:
            depuis_fx = x_fxtwitter.derniers_tweets(handle)
            sources.append("fxtwitter(" + str(len(depuis_fx)) + ")")
        except x_fxtwitter.ErreurFxtwitter as e:
            print("[source] fxtwitter indisponible : " + str(e)[:90])

        # X seulement en secours. Il refuse (429) les machines GitHub depuis
        # le 22/09 : l'interroger quand fxtwitter a repondu coutait 48 s de
        # reessais a chaque passage, pour rien.
        if not depuis_fx:
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

        # Apify n'est PAS appele ici : il facture chaque tweet ramene.
        # C'est main.py qui le declenche, et seulement quand le compteur
        # gratuit dit qu'il a publie sans que les sources gratuites
        # n'aient rien rapporte. Voir complement_apify().

        if not depuis_fx and not depuis_x and not depuis_tg:
            raise ErreurSource("aucune source disponible")

        _DERNIERE = "+".join(sources) or "aucune"
        # Ordre de priorite : fxtwitter, X, puis l'apercu Telegram, plus pauvre.
        fusion = _fusionner(depuis_fx, depuis_x, depuis_tg)
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
