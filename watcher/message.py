"""
Mise en forme du message Telegram.

Volontairement minimal : la paire, le sens, et les seuls chiffres
actionnables (entree, stop, TP). Tout le reste — resume, PnL, statut
detaille, extrait du post — a ete retire : l'alerte doit se lire d'un coup
d'oeil sur un telephone, et le lien permet d'aller voir le contexte.
"""

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


def _date(brut) -> str:
    """Date du post en JJ/MM/AAAA a HHhMM, ou chaine vide si illisible."""
    if not brut:
        return ""
    from datetime import datetime
    texte = str(brut).strip()

    try:
        return datetime.fromisoformat(
            texte.replace("Z", "+00:00")).strftime("%d/%m/%Y a %Hh%M")
    except Exception:
        pass

    morceaux = texte.split()
    if len(morceaux) >= 6 and morceaux[1] in _MOIS:
        try:
            heure = morceaux[3].split(":")
            return "{:02d}/{:02d}/{} a {}h{}".format(
                int(morceaux[2]), _MOIS[morceaux[1]], morceaux[5],
                heure[0], heure[1])
        except Exception:
            pass
    return ""


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

    if analyse.get("entree") is not None:
        lignes.append("Entry : <b>" + _nombre(analyse["entree"]) + "</b>" + _marque("entree"))
    elif analyse.get("zone_entree"):
        lignes.append("Entry : <b>" + _echapper(analyse["zone_entree"]) + "</b>" + _marque("entree"))

    # Le stop porte toujours sa provenance : lu dans le texte (rien a
    # signaler), lu sur le graphique, ou calcule ici faute d'etre lisible.
    # Un stop estime ne doit jamais pouvoir passer pour un stop annonce.
    if analyse.get("stop_loss") is not None:
        source = analyse.get("stop_source")
        if source == "estime":
            pct = analyse.get("stop_pct")
            note = (" <i>(est. " + ("%g" % pct).replace(".", ",") + " %)</i>"
                    if pct else " <i>(estime)</i>")
            prefixe = "~"
        else:
            note = " <i>(chart)</i>" if source == "chart" else ""
            prefixe = ""
        lignes.append("Stop : <b>" + prefixe + _nombre(analyse["stop_loss"])
                      + "</b>" + note)

    tps = analyse.get("take_profits") or []
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
