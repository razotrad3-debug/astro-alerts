"""Envoi et mise a jour des alertes Telegram.

Les fonctions d'envoi renvoient l'identifiant du message plutot qu'un
simple booleen : il permet de MODIFIER une alerte deja publiee. Le compte
surveille supprime et republie regulierement un post dans les minutes qui
suivent (constate le 16/09/2026 : 22h09 supprime, republie a 22h13 avec le
TP en plus). Sans cet identifiant, la seule option etait d'envoyer une
deuxieme alerte quasi identique.
"""
import requests

import config

_TIMEOUT = 20


def _identifiant(reponse) -> int:
    """message_id renvoye par Telegram, ou 0 si la reponse ne le porte pas."""
    try:
        return int(reponse.json()["result"]["message_id"])
    except Exception:
        return 0


def envoyer(texte: str):
    """Envoie un message HTML. Renvoie le message_id, ou 0 en cas d'echec."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[telegram] token ou chat_id manquant, message non envoye")
        return 0
    url = "https://api.telegram.org/bot" + config.TELEGRAM_BOT_TOKEN + "/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": texte,
            "parse_mode": "HTML",
            # Sans ca, Telegram colle une grosse carte d'apercu sous chaque
            # alerte : du bruit qui noie les trois chiffres qui comptent.
            "disable_web_page_preview": True,
        }, timeout=_TIMEOUT)
        if r.status_code >= 400:
            print("[telegram] erreur " + str(r.status_code) + " : " + r.text[:200])
            return 0
        return _identifiant(r)
    except Exception as e:
        print("[telegram] envoi impossible : " + str(e))
        return 0


def envoyer_photo(url_image: str, legende: str):
    """Envoie l'image du tweet avec l'analyse en legende.

    La legende Telegram est plafonnee a 1024 caracteres : au-dela, on
    retombe sur un message texte pour ne rien tronquer d'important.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return 0
    if len(legende) > 1024:
        return envoyer(legende)
    url = "https://api.telegram.org/bot" + config.TELEGRAM_BOT_TOKEN + "/sendPhoto"
    try:
        r = requests.post(url, json={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "photo": url_image,
            "caption": legende,
            "parse_mode": "HTML",
        }, timeout=_TIMEOUT)
        if r.status_code >= 400:
            # Telegram refuse parfois de recuperer l'image lui-meme
            # (hotlink, taille) : le texte seul vaut mieux que rien.
            return envoyer(legende)
        return _identifiant(r)
    except Exception:
        return envoyer(legende)


def _appel(methode: str, corps: dict) -> bool:
    """Appelle l'API Telegram, en tolerant le cas 'rien n'a change'."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
    corps = dict(corps, chat_id=config.TELEGRAM_CHAT_ID)
    try:
        r = requests.post(
            "https://api.telegram.org/bot" + config.TELEGRAM_BOT_TOKEN
            + "/" + methode, json=corps, timeout=_TIMEOUT)
        if r.status_code < 400:
            return True
        # Telegram refuse une modification qui ne change rien. Ce n'est pas
        # une erreur de notre point de vue : l'alerte affichee est deja la
        # bonne, il n'y a rien a corriger.
        if "not modified" in r.text.lower():
            return True
        print("[telegram] " + methode + " a repondu " + str(r.status_code)
              + " : " + r.text[:200])
        return False
    except Exception as e:
        print("[telegram] " + methode + " impossible : " + str(e))
        return False


def modifier(message_id: int, texte: str, url_image: str = "") -> bool:
    """Remplace le contenu d'une alerte deja publiee.

    Sert quand le compte supprime son post et le republie enrichi : plutot
    que d'envoyer une deuxieme alerte presque identique, on corrige celle
    qui est deja dans la conversation.

    Une legende de photo est plafonnee a 1024 caracteres, comme a l'envoi.
    """
    if not message_id:
        return False

    if url_image and len(texte) <= 1024:
        # editMessageMedia remplace l'image ET la legende en un seul appel :
        # le graphique republie est souvent re-televerse, donc different.
        if _appel("editMessageMedia", {
                "message_id": message_id,
                "media": {"type": "photo", "media": url_image,
                          "caption": texte, "parse_mode": "HTML"}}):
            return True
        # Telegram refuse parfois de recharger l'image : la legende seule
        # porte l'essentiel, le graphique d'origine reste lisible.
        return _appel("editMessageCaption", {
            "message_id": message_id, "caption": texte, "parse_mode": "HTML"})

    if url_image:
        return _appel("editMessageCaption", {
            "message_id": message_id, "caption": texte, "parse_mode": "HTML"})

    return _appel("editMessageText", {
        "message_id": message_id, "text": texte, "parse_mode": "HTML",
        "disable_web_page_preview": True})
