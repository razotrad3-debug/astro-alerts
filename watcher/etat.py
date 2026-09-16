"""
Memoire du watcher : quel tweet a deja ete traite.

Sans ca, chaque passage du cron re-alerterait sur les memes tweets. Le
fichier est volontairement minuscule et lisible a la main : sur GitHub
Actions il est commite dans le repo apres chaque run.
"""
import hashlib
import json
import os
import re

import config

_MAX_IDS = 200  # on ne garde qu'une fenetre recente, le fichier reste petit

_RE_MEDIA = re.compile(r"/media/([A-Za-z0-9_\-]+)")
_RE_LIEN = re.compile(r"https?://\S+")
_RE_BRUIT = re.compile(r"[^a-z0-9]+")


def empreinte(msg: dict) -> str:
    """Signature de CONTENU d'un post, stable d'une source a l'autre.

    L'identifiant ne suffit pas. Quand la chaine Telegram relaie un tweet
    sans lien /status/, x_telegram lui attribue "tg-<num>", qui ne pourra
    jamais correspondre au numero de tweet vu sur X. Le meme post partait
    donc DEUX FOIS en alerte, a quelques minutes d'ecart — l'ecart etant
    celui du relai Telegram, d'ou deux horodatages differents pour un seul
    et meme post.

    L'identifiant media de twimg, lui, est le meme quelle que soit la
    source. Verifie sur les 32 posts a graphique du compte : 32 media
    distincts, aucun reutilise d'un tweet a l'autre. C'est donc une cle
    sure ici — deux messages qui la partagent sont le meme post.

    Sans image, on retombe sur un prefixe de texte normalise. Un PREFIXE,
    parce que l'apercu Telegram coupe vers 190 caracteres : comparer les
    textes entiers ferait diverger la version courte de la version longue.
    """
    for u in (msg.get("images") or []):
        m = _RE_MEDIA.search(str(u))
        if m:
            return "img:" + m.group(1)

    texte = _RE_BRUIT.sub("", _RE_LIEN.sub(" ", (msg.get("texte") or "").lower()))
    if len(texte) < 20:
        return ""      # trop court pour distinguer deux posts sans risque
    return "txt:" + hashlib.sha1(texte[:120].encode()).hexdigest()[:16]


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


def horodatage(nom: str):
    """Dernier instant (epoch) enregistre sous ce nom, ou 0."""
    try:
        return float(charger().get("_horodatages", {}).get(nom, 0))
    except Exception:
        return 0.0


def poser_horodatage(nom: str) -> None:
    """Note maintenant sous ce nom, sans toucher au reste de la memoire.

    Chaque passage GitHub est un processus neuf : une variable en memoire ne
    survivrait pas. Il faut donc ecrire sur disque pour espacer une source
    facturee d'un passage a l'autre.
    """
    import time as _t
    etat = charger()
    etat.setdefault("_horodatages", {})[nom] = _t.time()
    sauver(etat)


def cle(handle: str, source: str = "") -> str:
    """Cle de memoire, propre a chaque source.

    Les identifiants ne vivent pas dans le meme espace selon la source :
    X donne des numeros de tweet, Telegram des numeros de message. Melanger
    les deux ferait croire, a chaque basculement, que tout est nouveau — et
    rejouerait tout l'historique de l'autre source en alertes.
    """
    return handle + "@" + source if source else handle


def deja_vus(etat: dict, handle: str) -> list:
    return list(etat.get(handle, {}).get("ids", []))


def empreintes_vues(etat: dict, handle: str) -> set:
    """Signatures de contenu deja traitees, pour ce handle."""
    return set(etat.get(handle, {}).get("empreintes", []))


def deja_traite(etat: dict, handle: str, msg: dict) -> bool:
    """Ce post est-il deja passe, sous n'importe quel identifiant ?"""
    if msg.get("id") in set(deja_vus(etat, handle)):
        return True
    e = empreinte(msg)
    return bool(e) and e in empreintes_vues(etat, handle)


def marquer(etat: dict, handle: str, ids, messages=()) -> None:
    """Note des identifiants vus, et les empreintes des messages fournis."""
    bloc = etat.setdefault(handle, {})
    connus = list(bloc.get("ids", []))
    for i in ids:
        if i not in connus:
            connus.append(i)
    bloc["ids"] = connus[-_MAX_IDS:]

    empreintes = list(bloc.get("empreintes", []))
    for m in messages or ():
        e = empreinte(m) if isinstance(m, dict) else str(m or "")
        if e and e not in empreintes:
            empreintes.append(e)
    bloc["empreintes"] = empreintes[-_MAX_IDS:]


def est_premier_run(etat: dict, handle: str) -> bool:
    return handle not in etat


def fusionner(local: dict, distant: dict) -> dict:
    """Reunit deux versions de la memoire sans rien perdre.

    Quand deux passages ecrivent en meme temps, git se retrouve avec deux
    state.json divergents et ne sait pas les reconcilier : le rebase echoue
    et l'un des deux passages perd son ecriture — donc re-alerte au passage
    suivant. On prend ici l'union des identifiants et des empreintes, et la
    plus grande valeur des horodatages et compteurs, qui ne font que croitre.
    """
    sortie = dict(distant or {})

    for cle_, bloc in (local or {}).items():
        if cle_.startswith("_") or not isinstance(bloc, dict):
            continue
        ref = dict(sortie.get(cle_) or {})
        for champ in ("ids", "empreintes"):
            reunion = list(ref.get(champ, []))
            for v in bloc.get(champ, []):
                if v not in reunion:
                    reunion.append(v)
            ref[champ] = reunion[-_MAX_IDS:]
        sortie[cle_] = ref

    for champ in ("_horodatages", "_compteurs"):
        reunion = dict((distant or {}).get(champ) or {})
        for nom, v in ((local or {}).get(champ) or {}).items():
            autre = reunion.get(nom, 0)
            try:
                gagnant = max(float(v), float(autre))
                # Les compteurs de tweets sont des entiers : les rendre en
                # flottant ferait diverger leur ecriture dans state.json a
                # chaque fusion, pour rien.
                if isinstance(v, int) and isinstance(autre, (int, float)):
                    gagnant = int(gagnant)
                reunion[nom] = gagnant
            except Exception:
                reunion.setdefault(nom, v)
        if reunion:
            sortie[champ] = reunion

    return sortie
