"""
Recuperation des tweets via Apify — la voie gratuite.

Apify offre 5 $ de credits par mois, renouveles. Avec un acteur facture au
resultat (~0,25 $ / 1000), en ne ramenant que quelques tweets par passage,
un cron de 15 min tient dans l'enveloppe offerte.

Chaque acteur a son propre format d'entree et de sortie. On garde donc
l'identifiant de l'acteur et le nom du champ "handle" configurables, et
`main.py --test` affiche la reponse brute quand rien n'est reconnu.
"""
import requests

import config
from . import x_api

_TIMEOUT = 120  # un acteur Apify demarre un conteneur : c'est lent au premier appel

# L'API attend l'acteur sous la forme "auteur~nom" ; les gens copient souvent
# "auteur/nom" depuis l'URL du store, donc on accepte les deux.
_BASE = "https://api.apify.com/v2/acts/{acteur}/run-sync-get-dataset-items"


class ErreurApify(Exception):
    pass


def _acteur() -> str:
    return config.APIFY_ACTEUR.replace("/", "~").strip()


def _entree(handle: str) -> dict:
    """Entree de l'acteur.

    Les scrapers X d'Apify acceptent presque tous `twitterHandles` et une
    limite de resultats. On envoie plusieurs variantes de la limite : un
    acteur ignore simplement les cles qu'il ne connait pas, alors qu'en
    oublier une ferait ramener (et facturer) bien plus de tweets que voulu.
    """
    return {
        "twitterHandles": [handle],
        "maxItems": config.APIFY_MAX,
        "maxTweetsPerQuery": config.APIFY_MAX,
        "tweetsDesired": config.APIFY_MAX,
        "sort": "Latest",
        "includeSearchTerms": False,
    }


def derniers_tweets(handle: str, brut_aussi: bool = False):
    """Les derniers tweets d'un compte via Apify, au meme format que x_api."""
    if not config.APIFY_TOKEN:
        raise ErreurApify("APIFY_TOKEN manquant dans le .env.")

    url = _BASE.format(acteur=_acteur())
    try:
        r = requests.post(
            url,
            params={"token": config.APIFY_TOKEN, "limit": config.APIFY_MAX},
            json=_entree(handle),
            timeout=_TIMEOUT,
        )
    except Exception as e:
        raise ErreurApify("Apify injoignable : " + str(e))

    if r.status_code in (401, 403):
        raise ErreurApify("Token Apify refuse (" + str(r.status_code) + ").")
    if r.status_code == 404:
        raise ErreurApify(
            "Acteur introuvable : " + _acteur() + ". Verifie APIFY_ACTEUR "
            "(forme 'auteur~nom', visible dans l'URL du store Apify)."
        )
    if r.status_code == 402:
        raise ErreurApify("Credits Apify epuises pour ce mois (402).")
    if r.status_code >= 400:
        raise ErreurApify("Apify a repondu " + str(r.status_code) + " : " + r.text[:300])

    try:
        donnees = r.json()
    except Exception:
        raise ErreurApify("Reponse Apify illisible : " + r.text[:300])

    # run-sync-get-dataset-items renvoie directement la liste des resultats.
    bruts = donnees if isinstance(donnees, list) else x_api._liste_tweets(donnees)

    # Certains acteurs glissent un objet d'erreur dans le dataset au lieu de
    # renvoyer un code HTTP : sans ca on croirait a un compte sans tweets.
    if len(bruts) == 1 and isinstance(bruts[0], dict) and bruts[0].get("error"):
        raise ErreurApify("Acteur Apify en erreur : " + str(bruts[0])[:300])

    sortie = x_api.normaliser(bruts, handle)
    if brut_aussi:
        return sortie, donnees
    return sortie
