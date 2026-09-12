"""Envoi des alertes Telegram (meme approche que mikemike-scanner)."""
import requests

import config

_TIMEOUT = 20


def envoyer(texte: str) -> bool:
    """Envoie un message HTML. Retourne True si Telegram l'a accepte."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[telegram] token ou chat_id manquant, message non envoye")
        return False
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
            return False
        return True
    except Exception as e:
        print("[telegram] envoi impossible : " + str(e))
        return False


def envoyer_photo(url_image: str, legende: str) -> bool:
    """Envoie l'image du tweet avec l'analyse en legende.

    La legende Telegram est plafonnee a 1024 caracteres : au-dela, on
    retombe sur un message texte pour ne rien tronquer d'important.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return False
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
        return True
    except Exception:
        return envoyer(legende)
