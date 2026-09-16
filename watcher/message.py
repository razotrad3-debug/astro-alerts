"""
Mise en forme du message Telegram.

Volontairement minimal : la paire, le sens, et les seuls chiffres
actionnables (entree, stop, TP). Tout le reste — resume, PnL, statut
detaille, extrait du post — a ete retire : l'alerte doit se lire d'un coup
d'oeil sur un telephone, et le lien permet d'aller voir le contexte.
"""
import config

_EMOJI_SENS = {"short": "\U0001F534", "long": "\U0001F7E2"}


# Mention discrete du type de post. Vide pour une entree : c'est le cas
# qui interesse, il n'a pas besoin d'etiquette.
_MENTION = {
    "ouverture": "",
    "intention": " — <i>a venir</i>",
    "en_cours": " · <i>suivi</i>",
    "cloture": " · <i>cloture</i>",
    "analyse": " · <i>analyse</i>",
}


def _echapper(t) -> str:
    """Telegram en mode HTML : seuls &, < et > doivent etre echappes."""
    if t is None:
        return ""
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _aerer(texte: str) -> str:
    """Ne garde que les sauts de ligne qui suivent une phrase terminee.

    Le modele coupe parfois au milieu d'une phrase : on recolle ces
    morceaux-la, et on normalise les paragraphes restants a une ligne vide.
    Garantie mecanique, plutot que de s'en remettre a la consigne.
    """
    import re
    if not texte:
        return ""
    # On marque d'abord les sauts LEGITIMES — ceux qui suivent une phrase
    # terminee — pour qu'ils survivent au nettoyage qui suit.
    texte = re.sub(r"([.!?:…])[ \t]*\n+[ \t]*", lambda m: m.group(1) + "\x00", texte)
    # Tout saut restant coupait une phrase : il redevient une espace.
    texte = re.sub(r"[ \t]*\n+[ \t]*", " ", texte)
    # Puis les sauts legitimes deviennent des paragraphes.
    texte = texte.replace("\x00", "\n\n")
    return texte.strip()


def _prix(v):
    """La valeur si c'est un prix affichable, None sinon.

    Le modele renvoie parfois null, 0 ou une chaine vide a la place d'un
    prix qu'il n'a pas lu. Sans ce filtre, l'alerte affichait "TP : " tout
    court, ou "TP : 0" — pire qu'une ligne absente, puisque ca se lit comme
    une information.
    """
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except Exception:
        return None
    if f <= 0 or f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _nombre(v) -> str:
    """Affiche un prix sans notation scientifique ni zeros inutiles."""
    if v is None:
        return ""
    try:
        f = float(v)
    except Exception:
        return _echapper(v)
    if f == int(f) and abs(f) < 1e15:
        return "{:,}".format(int(f)).replace(",", " ")
    return ("{:,.8f}".format(f)).rstrip("0").rstrip(".").replace(",", " ")


# Les sources ne datent pas pareil : Telegram rend de l'ISO, Apify et X le
# format Twitter historique ("Sat Sep 12 21:06:13 +0000 2026"). On ne passe
# pas par strptime avec %b, qui depend de la langue du systeme et echouerait
# sur une machine francaise.
_MOIS = {m: i + 1 for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}


def _decalage(brut: str):
    """Fuseau d'une date Twitter ("+0000"), ou UTC si illisible."""
    from datetime import timedelta, timezone
    try:
        signe = -1 if brut[0] == "-" else 1
        return timezone(signe * timedelta(hours=int(brut[1:3]),
                                          minutes=int(brut[3:5])))
    except Exception:
        return timezone.utc


def _horodatage(brut):
    """Datetime AVEC fuseau, depuis l'un ou l'autre format de source, ou None.

    Les deux sources datent en UTC : Telegram rend de l'ISO avec un +00:00,
    X et Apify le format historique ("Sat Sep 12 21:06:13 +0000 2026"). On
    conserve ce fuseau au lieu de le perdre, sinon la conversion en heure
    locale plus bas n'aurait rien sur quoi s'appuyer.
    """
    from datetime import datetime, timezone
    texte = str(brut).strip()

    try:
        d = datetime.fromisoformat(texte.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        pass

    morceaux = texte.split()
    if len(morceaux) >= 6 and morceaux[1] in _MOIS:
        try:
            h, m, s = (int(x) for x in morceaux[3].split(":"))
            return datetime(int(morceaux[5]), _MOIS[morceaux[1]],
                            int(morceaux[2]), h, m, s,
                            tzinfo=_decalage(morceaux[4]))
        except Exception:
            pass
    return None


_ZONE = None


def _zone():
    """Fuseau d'affichage, resolu une fois pour toutes.

    zoneinfo a besoin d'une base de fuseaux : presente sur les runners
    Linux, absente de Windows — d'ou le paquet tzdata dans requirements.
    Si malgre tout elle manque, on retombe sur le fuseau de la machine
    plutot que sur UTC : c'est faux la moitie de l'annee, mais moins
    souvent que d'afficher l'heure de Greenwich a quelqu'un a Paris.
    """
    global _ZONE
    if _ZONE is None:
        try:
            from zoneinfo import ZoneInfo
            _ZONE = ZoneInfo(config.FUSEAU)
        except Exception as e:
            print("[message] fuseau " + str(config.FUSEAU) + " indisponible ("
                  + str(e) + "), repli sur l'heure locale de la machine.")
            _ZONE = False
    return _ZONE or None


def _date(brut) -> str:
    """Date du post en heure LOCALE, JJ/MM/AAAA a HHhMM.

    Les sources datent en UTC. Affichee telle quelle, une publication de
    23h08 a Paris s'annoncait "21h08" — deux heures avant d'avoir eu lieu,
    ce qui rendait l'horodatage inutilisable pour juger de la fraicheur.
    """
    if not brut:
        return ""
    d = _horodatage(brut)
    if d is None:
        return ""
    try:
        return d.astimezone(_zone()).strftime("%d/%m/%Y a %Hh%M")
    except Exception:
        return d.strftime("%d/%m/%Y a %Hh%M")


def construire(tweet: dict, analyse: dict) -> str:
    lien = tweet.get("url", "")

    if analyse.get("erreur"):
        return ("⚠️ Analyse impossible\n"
                + '<a href="' + lien + '">voir le post</a>')

    sens = (analyse.get("sens") or "").lower()
    ticker = analyse.get("ticker") or ""
    statut = (analyse.get("statut") or "").lower()

    # Tous les posts a photo sont transmis, pas seulement les entrees : le
    # titre doit donc rester lisible quand il n'y a aucune position.
    if sens in ("short", "long"):
        titre = (_EMOJI_SENS[sens] + " <b>" + _echapper(ticker or "?")
                 + " : " + _echapper(sens.upper()) + "</b>")
        titre += _MENTION.get(statut, "")
    else:
        # Sans position, le titre porte deja l'information : inutile d'y
        # accoler "· analyse", ce serait dit deux fois.
        titre = "📊 <b>" + _echapper(ticker or "Analyse") + "</b>"
        if ticker:
            titre += _MENTION.get(statut, "")
    lignes = [titre]

    # Un chiffre absent du texte a ete lu sur le graphique, qui montre souvent
    # un trade anterieur. On le marque sans faire une ligne de plus.
    hors = analyse.get("chiffres_hors_texte") or []

    def _marque(champ):
        return " <i>(chart)</i>" if champ in hors else ""

    entree = _prix(analyse.get("entree"))
    if entree is not None:
        lignes.append("Entry : <b>" + _nombre(entree) + "</b>" + _marque("entree"))
    elif analyse.get("zone_entree"):
        lignes.append("Entry : <b>" + _echapper(analyse["zone_entree"]) + "</b>" + _marque("entree"))

    # Le stop porte toujours sa provenance : lu dans le texte (rien a
    # signaler), lu sur le graphique, ou calcule ici faute d'etre lisible.
    # Un stop estime ne doit jamais pouvoir passer pour un stop annonce.
    stop = _prix(analyse.get("stop_loss"))
    if stop is not None:
        source = analyse.get("stop_source")
        if source == "estime":
            pct = analyse.get("stop_pct")
            note = (" <i>(est. " + ("%g" % pct).replace(".", ",") + " %)</i>"
                    if pct else " <i>(estime)</i>")
            prefixe = "~"
        else:
            note = " <i>(chart)</i>" if source == "chart" else ""
            prefixe = ""
        lignes.append("Stop : <b>" + prefixe + _nombre(stop) + "</b>" + note)

    # Pas d'objectif lisible : pas de ligne du tout. On ne garde que les
    # prix reels, sans doublon, dans l'ordre donne par le modele.
    tps, vus = [], set()
    for x in (analyse.get("take_profits") or []):
        p = _prix(x)
        if p is not None and p not in vus:
            vus.add(p)
            tps.append(p)
    if tps:
        lignes.append("TP : " + " · ".join(_nombre(x) for x in tps) + _marque("TP"))

    if analyse.get("resume"):
        lignes.append("")
        lignes.append(_echapper(_aerer(analyse["resume"])))

    lignes.append("")
    quand = _date(tweet.get("date"))
    lignes.append('<a href="' + lien + '">X</a>'
                  + ("  ·  <i>" + quand + "</i>" if quand else ""))
    return "\n".join(lignes)
