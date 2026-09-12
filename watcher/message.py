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


def _date(brut) -> str:
    """Date du post en JJ/MM/AAAA a HHhMM, ou chaine vide si illisible."""
    if not brut:
        return ""
    texte = str(brut).strip().replace("Z", "+00:00")
    try:
        from datetime import datetime
        d = datetime.fromisoformat(texte)
    except Exception:
        return ""
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

    if analyse.get("entree") is not None:
        lignes.append("Entry : <b>" + _nombre(analyse["entree"]) + "</b>" + _marque("entree"))
    elif analyse.get("zone_entree"):
        lignes.append("Entry : <b>" + _echapper(analyse["zone_entree"]) + "</b>" + _marque("entree"))

    # Le stop n'est plus affiche : sur ce compte il vient presque toujours du
    # graphique et non du texte, donc il decrit souvent un trade anterieur.
    # Il reste extrait et disponible dans l'analyse si on veut le remettre.

    tps = analyse.get("take_profits") or []
    if tps:
        lignes.append("TP : " + " · ".join(_nombre(x) for x in tps) + _marque("TP"))

    if analyse.get("resume"):
        lignes.append("")
        lignes.append(_echapper(analyse["resume"]))

    lignes.append("")
    quand = _date(tweet.get("date"))
    lignes.append('<a href="' + lien + '">X</a>'
                  + ("  ·  <i>" + quand + "</i>" if quand else ""))
    return "\n".join(lignes)
