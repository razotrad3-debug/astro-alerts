"""
Memoire du watcher : quel tweet a deja ete traite.

Sans ca, chaque passage du cron re-alerterait sur les memes tweets. Le
fichier est volontairement minuscule et lisible a la main : sur GitHub
Actions il est commite dans le repo apres chaque run.
"""
import json
import os

import config

_MAX_IDS = 200  # on ne garde qu'une fenetre recente, le fichier reste petit


def charger() -> dict:
    if not os.path.exists(config.STATE_FILE):
        return {}
    try:
        with open(config.STATE_FILE, "r", encoding="utf-8") as f:
            donnees = json.load(f)
        return donnees if isinstance(donnees, dict) else {}
    except Exception:
        # Fichier corrompu : on repart de zero plutot que de planter. Le
        # garde-fou SILENCE_PREMIER_RUN evite le deluge d'alertes.
        return {}


def sauver(etat: dict) -> None:
    try:
        with open(config.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(etat, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[etat] sauvegarde impossible : " + str(e))


def deja_vus(etat: dict, handle: str) -> list:
    return list(etat.get(handle, {}).get("ids", []))


def marquer(etat: dict, handle: str, ids) -> None:
    bloc = etat.setdefault(handle, {})
    connus = list(bloc.get("ids", []))
    for i in ids:
        if i not in connus:
            connus.append(i)
    bloc["ids"] = connus[-_MAX_IDS:]


def est_premier_run(etat: dict, handle: str) -> bool:
    return handle not in etat
