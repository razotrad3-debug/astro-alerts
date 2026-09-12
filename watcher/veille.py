"""
Detection gratuite d'un nouveau tweet, sans lire le tweet.

Le probleme : Apify voit tout mais facture chaque tweet ramene, donc
l'interroger toutes les 5 minutes coute ~66 $/mois. Telegram et X
syndication sont gratuits mais l'un est incomplet et l'autre refuse souvent.

La solution : un compteur. Les miroirs publics fxtwitter et vxtwitter
exposent le nombre total de tweets d'un compte, gratuitement et en 0,2 s.
Quand ce nombre bouge, il a publie quelque chose. On ne paie Apify qu'a ce
moment-la, et seulement si les sources gratuites n'ont rien rapporte.
"""
import requests

_TIMEOUT = 15
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

_MIROIRS = [
    ("https://api.fxtwitter.com/{h}", ("user", "tweets")),
    ("https://api.vxtwitter.com/{h}", (None, "tweet_count")),
]


def compteur(handle: str):
    """Nombre total de tweets du compte, ou None si aucun miroir ne repond.

    Les deux miroirs ne donnent pas le meme chiffre (caches differents) :
    on ne compare donc jamais l'un a l'autre, seulement un miroir a
    lui-meme. D'ou le nom du miroir renvoye avec la valeur.
    """
    for gabarit, (bloc, champ) in _MIROIRS:
        try:
            r = requests.get(gabarit.format(h=handle.lstrip("@")),
                             headers={"User-Agent": _UA}, timeout=_TIMEOUT)
            if r.status_code != 200:
                continue
            d = r.json()
            source = (d.get(bloc) or {}) if bloc else d
            valeur = source.get(champ)
            if isinstance(valeur, int):
                nom = gabarit.split("//")[1].split(".")[1]
                return nom, valeur
        except Exception:
            continue
    return None, None


def a_publie(handle: str, etat) -> bool:
    """Le compteur a-t-il bouge depuis la derniere verification ?

    Premiere fois : on enregistre sans rien declencher, sinon on paierait
    un appel Apify a chaque nouveau deploiement.
    """
    nom, valeur = compteur(handle)
    if valeur is None:
        # Aucun miroir : on ne peut pas savoir. On ne declenche pas — les
        # sources gratuites tournent quand meme, et le filet horaire reste.
        return False

    memoire = etat.charger()
    cles = memoire.setdefault("_compteurs", {})
    cle = handle + "@" + nom
    ancien = cles.get(cle)

    if ancien != valeur:
        cles[cle] = valeur
        etat.sauver(memoire)
    if ancien is None:
        print("[veille] compteur initialise a " + str(valeur)
              + " (" + nom + "), rien a rattraper")
        return False
    if valeur == ancien:
        return False

    print("[veille] " + str(valeur - ancien) + " publication(s) detectee(s) "
          + "(" + nom + " : " + str(ancien) + " -> " + str(valeur) + ")")
    return True
