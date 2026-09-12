"""
Lecture du tweet par Claude : le texte + les captures d'ecran, et on en
ressort un trade structure.

Le point important : le modele doit avoir le droit de dire "je ne sais pas".
Un prix d'entree hallucine est pire que pas de prix du tout, parce qu'on
agirait dessus. D'ou les champs nullables et le champ "confiance".
"""
import base64
import copy
import json
import time

import anthropic
import requests

import config

_TIMEOUT_IMAGE = 30
_TAILLE_MAX = 4 * 1024 * 1024  # limite raisonnable par image

_TYPES_OK = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "image/gif": "image/gif",
    "image/webp": "image/webp",
}

_SYSTEME = """Tu analyses les publications d'un trader crypto sur X (Twitter).

Ton unique travail : determiner s'il annonce une position, et si oui, en
extraire les parametres exacts.

DEUX SOURCES, A EGALITE
Le texte du tweet compte autant que les images, souvent plus. Ce trader
annonce regulierement ses entrees en toutes lettres, sans capture :
  "Flipped the longs, into shorts (76k is coming)"      -> short BTC, ouverture
  "we went short at 79.4k"                              -> short BTC a 79400
  "79.3k is that confluence region where it's time to
   start another short"                                 -> intention, pas encore pris
Quand une image est jointe, c'est en general un graphique TradingView
annote, un ticket d'ordre ou une capture de PnL (Bybit, Binance, BloFin,
Bitunix, Hyperliquid...). Croise les deux : le texte donne souvent le prix
que l'image ne montre pas, et inversement.

LIRE UN CHART TRADINGVIEW
L'outil "position long/short" de TradingView dessine trois elements : une
ligne d'ENTREE, une zone de STOP d'un cote, une zone d'OBJECTIF de l'autre.
Sur un short, le stop est au-dessus de l'entree et l'objectif en dessous.
Des lignes annotees "TP 1", "TP 2" sont des objectifs intermediaires.

PIEGE MAJEUR : une boite de position tracee sur le graphique montre tres
souvent un trade PASSE ou une projection, pas celui qui est annonce dans le
tweet. Verifie toujours la coherence avant de rapporter un chiffre :
- Compare les dates. Si la boite commence plusieurs jours avant la derniere
  bougie, elle raconte un trade deja joue.
- Compare au prix courant affiche en haut du chart (O/H/L/C) et a l'etiquette
  de prix coloree sur l'axe. Une entree annoncee tres loin du prix actuel est
  suspecte.
- Compare au texte. EN CAS DE DESACCORD ENTRE LE TEXTE ET L'IMAGE, LE TEXTE
  FAIT FOI pour la position annoncee. Mets les chiffres de l'image dans
  "indices" en precisant qu'ils viennent d'un trade anterieur, et baisse la
  confiance a "moyenne" ou "basse".
N'attribue jamais a la position annoncee une entree ou un stop lus sur une
boite qui decrit visiblement un autre trade.

NOTATION DES PRIX
Convertis toujours en nombre entier reel :
  "76k" -> 76000        "79.4k" -> 79400       "1.2m" -> 1200000
  "76-77k" -> zone_entree "76000 - 77000", entree = null
N'ecris jamais 76 quand le trader ecrit 76k.

CE QUI COMPTE : L'ENTREE, PAS LE SUIVI
Le statut est le champ le plus important. Classe sans hesiter :

"ouverture" — il prend une position MAINTENANT :
  "Flipped the longs, into shorts"        "now flipping shorts into longs"
  "Entered short on X live too"           "Took a long, lower size"
  "Just shorted here"                     "Adding shorts here"
  "Started the short"                     "it's now time to flip those longs into shorts"

"intention" — il annonce un trade A VENIR, avec un sens et un niveau ou un
declencheur identifiable :
  "my next trade will be a short at 80k"
  "79.3k is that confluence region where it's time to start another short"
  "getting ready to flip long"            "will look to short into that zone"

"en_cours" — il commente une position DEJA ouverte. Aucune entree nouvelle :
  "Up 2000 points"                        "TP some more"
  "Shaved some here"                      "Short working out too"
  "still holding our shorts"              "We have touchdown"

"cloture" — il sort :
  "Long worked out"                       "fully closed the longs"
  "closed the rest here"

"analyse" — commentaire de marche, prevision de prix sans trade annonce,
pique aux autres traders, message communautaire :
  "76k is coming"                         "September will be red"
  "Good morning, dear friends"

Un message qui ferme une position ET en ouvre une autre est "ouverture" :
c'est la nouvelle entree qui interesse. Mentionne la fermeture dans le resume.
Une simple prevision de prix n'est PAS une intention : il faut qu'il dise
vouloir prendre la position.

LE TEST DECISIF POUR "ouverture"
Demande-toi : ce message est-il l'ANNONCE de l'entree, ou un commentaire sur
une position qu'il a DEJA annoncee ailleurs ?
Seule l'annonce elle-meme est "ouverture". Signes qu'il annonce maintenant :
un verbe d'action a l'instant ("Entered", "Just took", "I'm going long here",
"Flipped ... into ..."), ou une entree qu'il donne pour la premiere fois.
Signes qu'il commente une position DEJA prise -> "en_cours" :
  - il parle de la position comme acquise : "my longs", "our shorts",
    "this trade", "the position", "still holding"
  - il raconte le resultat ou le deroulement : gains, series de wins,
    "worked out", "and there's the drop", "TP some here", "shaved some"
  - il fait le bilan ou la pedagogie autour d'un trade en cours
  - le prix d'entree n'apparait que sur le graphique, comme rappel
Dans le doute entre "ouverture" et "en_cours", choisis "en_cours" :
une alerte manquee derange moins qu'une fausse alerte d'entree.

REGLES ABSOLUES
- Ne devine JAMAIS un chiffre. Si un prix n'est ni lisible dans l'image ni
  ecrit dans le texte, mets null. Un prix invente ferait perdre de l'argent.
- Une simple prevision de prix ("76k is coming", "September will be red")
  n'est ni une position ni une intention : statut "analyse".
- Un "flip" est a la fois une cloture et une ouverture : decris la NOUVELLE
  position, et mentionne celle qui vient d'etre fermee dans le resume.
- Sur une capture de PnL, l'entree est l'Entry Price / Prix d'entree, pas
  le prix actuel du marche (Mark Price).
- "Short" = vente a decouvert, pari baissier. "Long" = pari haussier. Sur un
  ticket d'ordre, Sell/Vendre = short, Buy/Acheter = long.
- Ce compte ne trade quasiment que le Bitcoin. Si aucun cashtag n'apparait
  ("Entered short on X live too", "Took a long, lower size"), le ticker est
  BTC. Ne mets null que si un AUTRE actif est explicitement nomme et
  ambigu ; lis le cashtag quand il y en a un.
- Beaucoup de ses posts sont du commentaire, des piques aux autres traders
  ou des annonces communautaires, sans aucun trade. C'est normal : mets
  position_annoncee = false et statut "analyse", n'invente pas de position.
- Si plusieurs positions apparaissent, decris la principale et mentionne
  les autres dans le resume.
- Ecris le resume et les indices en francais.
- Dans le resume, appelle-le "Astro". Jamais "le trader", jamais son pseudo.
- Le resume doit raconter le CONTENU du post, pas la fiche du trade. Le
  ticker, le sens et les prix sont deja affiches a cote : les repeter gaspille
  les seules lignes que le lecteur va lire. Dis plutot pourquoi il prend ce
  trade, ce qu'il observe sur le marche, ce qu'il annonce pour la suite.
  Mauvais : "Astro ouvre un long sur BTC vers 77 000 apres un rebond."
  Bon : "Il voit le support des 77k tenir apres la baisse de la semaine et
  attend une remontee vers les 81k. Il prend une taille reduite parce que
  le mouvement va contre la tendance de fond, et previent qu'il coupera
  vite si le niveau lache."

Appelle toujours l'outil rapport_trade pour repondre."""

_OUTIL = {
    "name": "rapport_trade",
    "description": "Transmet l'analyse structuree du tweet.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "position_annoncee": {
                "type": "boolean",
                "description": "true si une position est prise, annoncee comme imminente, en cours ou cloturee.",
            },
            "ticker": {
                "type": ["string", "null"],
                "description": "Actif, en majuscules, ex: BTC, ETH, SOL, HYPE. null si absent.",
            },
            "sens": {
                "type": ["string", "null"],
                "enum": ["short", "long", None],
                "description": "Sens de la position.",
            },
            "entree": {
                "type": ["number", "null"],
                "description": "Prix d'entree exact s'il est lisible. null sinon.",
            },
            "zone_entree": {
                "type": ["string", "null"],
                "description": "Zone d'entree quand c'est une fourchette, ex: 112400 - 113100.",
            },
            "stop_loss": {"type": ["number", "null"]},
            "take_profits": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Objectifs, du plus proche au plus lointain. Tableau vide si aucun.",
            },
            "levier": {
                "type": ["string", "null"],
                "description": "Ex: 10x, cross 25x. null si absent.",
            },
            "taille": {
                "type": ["string", "null"],
                "description": "Taille de position telle qu'affichee, ex: 0.5 BTC, 25000 USDT.",
            },
            "exchange": {"type": ["string", "null"]},
            "timeframe": {
                "type": ["string", "null"],
                "description": "Unite de temps du graphique, ex: 15m, 4H, 1D.",
            },
            "pnl": {
                "type": ["string", "null"],
                "description": "PnL affiche, ex: +1240 USDT (+18.2%).",
            },
            "statut": {
                "type": "string",
                "enum": ["ouverture", "intention", "en_cours", "cloture", "analyse", "inconnu"],
                "description": "ouverture = il entre maintenant ; intention = il annonce un trade a venir ; en_cours = suivi d une position deja ouverte ; analyse = pas de trade.",
            },
            "confiance": {
                "type": "string",
                "enum": ["haute", "moyenne", "basse"],
                "description": "haute = tout est lisible noir sur blanc ; basse = beaucoup d'interpretation.",
            },
            "indices": {
                "type": ["string", "null"],
                "description": "Ce que tu as reellement lu (citation du texte ou element de l'image) qui justifie l'extraction.",
            },
            "resume": {
                "type": "string",
                "description": "Ce qu'Astro RACONTE dans son post : son raisonnement, le contexte de marche, son plan, ce qu'il attend. 2 a 4 phrases en francais. Ne repete pas le ticker, le sens ni les prix, ils sont deja affiches a cote.",
            },
        },
        "required": [
            "position_annoncee", "ticker", "sens", "entree", "zone_entree",
            "stop_loss", "take_profits", "levier", "taille", "exchange",
            "timeframe", "pnl", "statut", "confiance", "indices", "resume",
        ],
    },
}


def _outil_permissif() -> dict:
    """Version assouplie du schema, utilisee si l'API refuse le schema strict.

    On enleve `strict`, les types nullables et les enums contenant null, et on
    ne rend obligatoires que les champs dont on a vraiment besoin. Le modele
    peut alors simplement omettre ce qu'il n'a pas lu — le reste du code lit
    tout via .get(), donc un champ absent ne casse rien.
    """
    outil = copy.deepcopy(_OUTIL)
    outil.pop("strict", None)
    schema = outil["input_schema"]
    schema.pop("additionalProperties", None)
    for prop in schema["properties"].values():
        if isinstance(prop.get("type"), list):
            concrets = [t for t in prop["type"] if t != "null"]
            prop["type"] = concrets[0] if concrets else "string"
        if isinstance(prop.get("enum"), list):
            prop["enum"] = [v for v in prop["enum"] if v is not None]
    schema["required"] = ["position_annoncee", "statut", "confiance", "resume"]
    return outil


def _telecharger(url: str):
    """Renvoie (media_type, donnees_base64) ou None si l'image est inutilisable."""
    try:
        r = requests.get(url, timeout=_TIMEOUT_IMAGE)
        if r.status_code >= 400:
            return None
        brut = r.content
        if not brut or len(brut) > _TAILLE_MAX:
            return None
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        media_type = _TYPES_OK.get(ctype)
        if media_type is None:
            # X renvoie parfois un Content-Type generique ; on retombe sur
            # l'extension, et a defaut sur jpeg qui couvre la majorite.
            bas = url.lower()
            if ".png" in bas:
                media_type = "image/png"
            elif ".webp" in bas:
                media_type = "image/webp"
            elif ".gif" in bas:
                media_type = "image/gif"
            else:
                media_type = "image/jpeg"
        return media_type, base64.standard_b64encode(brut).decode("utf-8")
    except Exception:
        return None


def _consigne_json() -> str:
    """Decrit le JSON attendu, genere depuis le schema de l'outil.

    Gemini n'a pas d'equivalent exact du "tool use" de Claude : on lui demande
    du JSON brut. Generer la consigne depuis _OUTIL evite que les deux
    fournisseurs derivent l'un de l'autre quand on ajoute un champ.
    """
    lignes = ["Reponds UNIQUEMENT par un objet JSON, sans texte autour,",
              "avec exactement ces cles :"]
    for nom, prop in _OUTIL["input_schema"]["properties"].items():
        types = prop.get("type")
        types = "|".join(types) if isinstance(types, list) else str(types)
        detail = prop.get("description", "")
        if prop.get("enum"):
            valeurs = [v for v in prop["enum"] if v is not None]
            detail += " Valeurs possibles : " + ", ".join(valeurs) + "."
        lignes.append('  "' + nom + '" (' + types + ') : ' + detail)
    lignes.append("Utilise null pour tout ce que tu n'as pas pu lire.")
    return "\n".join(lignes)


def _preparer(tweet: dict):
    """Telecharge les images et compose le message utilisateur.

    Retourne (images, invite) ou images est une liste de (media_type, base64).
    Cette representation est neutre : les deux fournisseurs la consomment.
    """
    images = []
    for url in tweet.get("images", []):
        res = _telecharger(url)
        if res is not None:
            images.append(res)

    texte = tweet.get("texte") or "(tweet sans texte)"
    invite = (
        "Compte : @" + str(tweet.get("handle")) + "\n"
        "Texte du tweet :\n" + texte + "\n\n"
        + (str(len(images)) + " capture(s) jointe(s)."
           if images else "Aucune image exploitable dans ce tweet.")
    )
    return images, invite


def _extraire_json(texte: str):
    """Recupere le premier objet JSON d'une reponse texte, ou None."""
    if not texte:
        return None
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut < 0 or fin <= debut:
        return None
    try:
        return json.loads(texte[debut:fin + 1])
    except Exception:
        return None


# ── Claude ────────────────────────────────────────────────

def _claude(images, invite) -> dict:
    if not config.ANTHROPIC_API_KEY:
        return {"erreur": "ANTHROPIC_API_KEY manquante (FOURNISSEUR_IA=anthropic)."}

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    contenu = [{"type": "image",
                "source": {"type": "base64", "media_type": mt, "data": b64}}
               for mt, b64 in images]
    contenu.append({"type": "text", "text": invite})

    def _appel(outil):
        return client.messages.create(
            model=config.MODELE,
            max_tokens=4000,
            system=_SYSTEME,
            tools=[outil],
            messages=[{"role": "user", "content": contenu}],
        )

    try:
        reponse = _appel(_OUTIL)
    except anthropic.BadRequestError as e:
        # Un 400 vient presque toujours du schema strict (types nullables,
        # enum avec null). On retente une fois en permissif avant d'abandonner.
        print("[vision] schema strict refuse, second essai en permissif : " + str(e)[:200])
        try:
            reponse = _appel(_outil_permissif())
        except Exception as e2:
            return {"erreur": "API Claude : " + str(e2)}
    except anthropic.APIError as e:
        return {"erreur": "API Claude : " + str(e)}

    if reponse.stop_reason == "refusal":
        return {"erreur": "Claude a refuse d'analyser ce contenu."}

    for bloc in reponse.content:
        if bloc.type == "tool_use" and bloc.name == "rapport_trade":
            return dict(bloc.input)

    texte = " ".join(b.text for b in reponse.content if b.type == "text").strip()
    out = _extraire_json(texte)
    if out is not None:
        return out
    return {"erreur": "Claude n'a pas renvoye d'analyse structuree.",
            "brut": texte[:500]}


# ── Gemini ────────────────────────────────────────────────

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"


def _gemini_un(modele: str, images, invite) -> dict:
    """Un appel a UN modele Gemini. Signale a part le quota journalier."""
    parts = [{"inline_data": {"mime_type": mt, "data": b64}} for mt, b64 in images]
    parts.append({"text": invite})

    corps = {
        "systemInstruction": {"parts": [{"text": _SYSTEME + "\n\n" + _consigne_json()}]},
        "contents": [{"role": "user", "parts": parts}],
        # temperature 0 : on veut une lecture, pas de la creativite.
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0},
    }

    # Le palier gratuit plafonne par minute ET par jour. Une rafale trop
    # rapide se rattrape en attendant ; un quota journalier epuise, non.
    r = None
    for essai in range(3):
        try:
            r = requests.post(
                _GEMINI_URL.format(m=modele),
                headers={"x-goog-api-key": config.GEMINI_API_KEY,
                         "Content-Type": "application/json"},
                json=corps, timeout=90,
            )
        except Exception as e:
            return {"erreur": "Gemini injoignable : " + str(e)}

        if r.status_code != 429:
            break

        if "perday" in r.text.lower().replace("_", "").replace(" ", ""):
            return {"erreur": "quota journalier epuise sur " + modele,
                    "_quota_jour": True}
        if essai == 2:
            break
        attente = 20 * (essai + 1)
        print("[vision] " + modele + " sature (429), nouvel essai dans "
              + str(attente) + "s...")
        time.sleep(attente)

    if r.status_code == 429:
        return {"erreur": "Gemini sature (429) sur " + modele + " apres 3 essais."}
    if r.status_code == 404:
        return {"erreur": "Modele inconnu : " + modele, "_quota_jour": True}
    if r.status_code >= 400:
        return {"erreur": "Gemini a repondu " + str(r.status_code) + " : " + r.text[:300]}

    try:
        donnees = r.json()
    except Exception:
        return {"erreur": "Reponse Gemini illisible : " + r.text[:300]}

    blocage = (donnees.get("promptFeedback") or {}).get("blockReason")
    if blocage:
        return {"erreur": "Gemini a refuse d'analyser ce contenu (" + str(blocage) + ")."}

    candidats = donnees.get("candidates") or []
    if not candidats:
        return {"erreur": "Gemini n'a renvoye aucune reponse."}

    morceaux = (candidats[0].get("content") or {}).get("parts") or []
    texte = "".join(m.get("text", "") for m in morceaux).strip()

    out = _extraire_json(texte)
    if out is not None:
        return out
    return {"erreur": "Gemini n'a pas renvoye de JSON exploitable.",
            "brut": texte[:500]}


def _gemini(images, invite) -> dict:
    """Essaie les modeles dans l'ordre jusqu'a en trouver un qui reponde.

    Le quota gratuit de Gemini est compte PAR MODELE (quota
    GenerateRequestsPerDayPerProjectPerModel-FreeTier, mesure a 20/jour sur
    gemini-3.6-flash). Enchainer plusieurs modeles multiplie donc la reserve
    quotidienne sans rien payer, et le service continue quand le premier
    est a sec.
    """
    if not config.GEMINI_API_KEY:
        return {"erreur": "GEMINI_API_KEY manquante (FOURNISSEUR_IA=gemini)."}

    derniere = None
    for modele in config.GEMINI_MODELES:
        res = _gemini_un(modele, images, invite)
        if res.get("_quota_jour"):
            print("[vision] " + modele + " : quota du jour epuise, modele suivant")
            derniere = res
            continue
        return res

    return derniere or {"erreur": "Aucun modele Gemini disponible."}


# ── Point d'entree ────────────────────────────────────────

def _dans_le_texte(valeur, texte: str) -> bool:
    """Ce nombre est-il ecrit dans le tweet ?

    Le trader ecrit "79.3k" la ou le modele renvoie 79300, d'ou les variantes.
    """
    try:
        v = float(valeur)
    except Exception:
        return False

    # On enleve espaces, virgules et apostrophes des nombres du texte pour
    # que "82 184,72" et "82184.72" se comparent.
    plat = texte.lower().replace(" ", "").replace(",", "").replace("'", "")

    milliers = v / 1000.0
    variantes = {
        str(int(v)),
        ("%g" % v),
        ("%g" % milliers) + "k",
        ("%.1f" % milliers).rstrip("0").rstrip(".") + "k",
        str(int(milliers)) + "k",
    }
    return any(c in plat for c in variantes if c)


def _controler_provenance(analyse: dict, tweet: dict) -> dict:
    """Signale les chiffres absents du tweet, donc lus uniquement sur l'image.

    Mesure faite sur un vrai post : le modele reprend volontiers le stop et
    les TP d'une boite TradingView qui decrit le trade PRECEDENT. Le champ
    reste affiche — il est souvent juste — mais il est marque, pour qu'une
    alerte ne presente jamais un stop invente comme un stop annonce.
    """
    if analyse.get("erreur") or not tweet.get("images"):
        return analyse

    texte = tweet.get("texte") or ""
    hors_texte = []

    if analyse.get("entree") is not None and not _dans_le_texte(analyse["entree"], texte):
        hors_texte.append("entree")
    if analyse.get("stop_loss") is not None and not _dans_le_texte(analyse["stop_loss"], texte):
        hors_texte.append("stop")
    tps = analyse.get("take_profits") or []
    if tps and not any(_dans_le_texte(t, texte) for t in tps):
        hors_texte.append("TP")

    analyse["chiffres_hors_texte"] = hors_texte
    if hors_texte and analyse.get("confiance") == "haute":
        # Des chiffres qu'on ne retrouve pas dans le tweet ne meritent pas
        # une confiance maximale, quoi qu'en dise le modele.
        analyse["confiance"] = "moyenne"
    return analyse


def analyser(tweet: dict) -> dict:
    """Analyse un tweet normalise et renvoie les champs decrits par _OUTIL.

    En cas d'echec (reseau, quota, refus), renvoie un dict avec 'erreur'
    rempli plutot que de lever : une alerte degradee vaut mieux qu'aucune.
    """
    images, invite = _preparer(tweet)

    try:
        if config.FOURNISSEUR_IA == "anthropic":
            out = _claude(images, invite)
        elif config.FOURNISSEUR_IA == "gemini":
            out = _gemini(images, invite)
        else:
            out = {"erreur": "FOURNISSEUR_IA inconnu : " + str(config.FOURNISSEUR_IA)
                             + " (attendu : gemini ou anthropic)"}
    except Exception as e:
        out = {"erreur": "Analyse impossible : " + str(e)}

    if not isinstance(out, dict):
        out = {"erreur": "Reponse d'analyse inattendue."}
    out["images_lues"] = len(images)
    return _controler_provenance(out, tweet)
