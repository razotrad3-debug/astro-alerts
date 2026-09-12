"""
Configuration centrale du watcher.
Tout se regle ici ou via le fichier .env (local) / les Secrets GitHub (Actions).
"""
import os


def _dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def path(nom: str) -> str:
    """Chemin absolu d'un fichier de travail (.env, state.json)."""
    return os.path.join(_dir(), nom)


# En local on lit le .env ; sur GitHub Actions il n'existe pas et les valeurs
# arrivent deja par l'environnement, donc l'echec est silencieux et normal.
try:
    from dotenv import load_dotenv
    load_dotenv(path(".env"))
except Exception:
    pass


def _bool(nom: str, defaut: bool) -> bool:
    brut = os.getenv(nom)
    if brut is None:
        return defaut
    return brut.strip().lower() in ("1", "true", "yes", "oui", "on")


def _int(nom: str, defaut: int) -> int:
    try:
        return int(os.getenv(nom, "").strip())
    except Exception:
        return defaut


# ── Qui on surveille ──────────────────────────────────────
# Plusieurs handles possibles, separes par des virgules, sans le @.
HANDLES = [h.strip().lstrip("@") for h in
           os.getenv("X_HANDLES", os.getenv("X_HANDLE", "")).replace(";", ",").split(",")
           if h.strip()]

# ── D'ou viennent les tweets ? ────────────────────────────
# "twitterapi" : payant (~9 $/mois), fiable — defaut
# "apify"      : gratuit MAIS inutilisable pour X sur le plan FREE (teste le
#                12/09/2026 : trois acteurs ramenent zero tweet, faute de
#                proxy residentiel ; X bloque les IP datacenter).
# "telegram"   : GRATUIT et fonctionnel — lit la chaine Telegram publique du
#                trader, qui relaie ses tweets (texte + image). Aucune cle.
SOURCE_X = os.getenv("SOURCE_X", "telegram").strip().lower()

# Chaine Telegram publique a lire quand SOURCE_X=telegram (le nom apres t.me/).
TELEGRAM_CANAL = os.getenv("TELEGRAM_CANAL", "AstronomerZero").strip()

# twitterapi.io — base et chemin configurables : si l'URL bouge, on corrige
# dans le .env sans toucher au code.
TWITTERAPI_KEY = os.getenv("TWITTERAPI_IO_KEY", "").strip()
TWITTERAPI_BASE = os.getenv("TWITTERAPI_IO_BASE", "https://api.twitterapi.io").rstrip("/")
TWITTERAPI_PATH = os.getenv("TWITTERAPI_IO_PATH", "/twitter/user/last_tweets")

# Apify — l'acteur (le scraper) est identifie par "auteur~nom". Les acteurs
# factures au resultat sont les moins chers ; voir le README.
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "").strip()
# xtdata~... accepte twitterHandles + maxItems (schema verifie).
APIFY_ACTEUR = os.getenv("APIFY_ACTEUR", "xtdata~twitter-x-user-tweets-scraper").strip()
# Chaque resultat ramene est facture. 5 suffit largement entre deux passages
# et fait tenir le mois dans les 5 $ offerts ; 20 les epuiserait.
APIFY_MAX = _int("APIFY_MAX", 5)

# ── Quelle IA lit les tweets ? ────────────────────────────
# "gemini"    : gratuit, teste et fonctionnel — defaut
# "anthropic" : payant, a essayer si Gemini se trompe sur les graphiques
FOURNISSEUR_IA = os.getenv("FOURNISSEUR_IA", "gemini").strip().lower()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODELE = os.getenv("ANTHROPIC_MODEL", "claude-opus-5").strip()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# Le quota gratuit est compte PAR MODELE (mesure : 20 requetes/jour sur
# gemini-3.6-flash). On en enchaine donc plusieurs : quand le quota du jour
# d'un modele est epuise, le suivant prend le relais, sans rien payer.
# Les "flash-lite" passent en premier : ils suffisent pour cette lecture.
GEMINI_MODELES = [m.strip() for m in os.getenv(
    "GEMINI_MODELS",
    "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.6-flash,gemini-2.5-flash"
).split(",") if m.strip()]

# Compatibilite : GEMINI_MODEL (au singulier) force un seul modele.
_un_seul = os.getenv("GEMINI_MODEL", "").strip()
if _un_seul:
    GEMINI_MODELES = [_un_seul]
GEMINI_MODELE = GEMINI_MODELES[0]

# ── Telegram ──────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# ── Comportement ──────────────────────────────────────────
# Fichier ou l'on retient le dernier tweet vu, pour ne pas re-alerter.
STATE_FILE = os.getenv("STATE_FILE", path("state.json"))

# Les reponses a d'autres comptes sont rarement des setups, et elles
# multiplient le volume. On les ignore par defaut.
IGNORER_REPONSES = _bool("IGNORER_REPONSES", True)
IGNORER_RETWEETS = _bool("IGNORER_RETWEETS", True)

# Quels statuts declenchent une alerte. Par defaut uniquement les ENTREES :
# une entree prise ("il flippe en short") ou annoncee ("mon prochain trade
# sera..."). Le suivi d'une position deja ouverte ("up 2000 points", "TP some
# more") n'apprend rien d'actionnable et noierait les vraies entrees.
# Pour tout recevoir : STATUTS_ALERTE=ouverture,intention,en_cours,cloture
STATUTS_ALERTE = [x.strip().lower() for x in
                  os.getenv("STATUTS_ALERTE", "ouverture,intention").split(",")
                  if x.strip()]

# Envoyer une alerte meme quand aucun trade n'est detecte (miroir complet).
ALERTER_SANS_TRADE = _bool("ALERTER_SANS_TRADE", False)

# Un tweet sans image ne contient presque jamais le detail d'une entree.
# Mis a True, on analyse quand meme le texte seul.
ANALYSER_SANS_IMAGE = _bool("ANALYSER_SANS_IMAGE", True)

# Au tout premier lancement, on note juste ou on en est sans rien envoyer,
# pour eviter de recevoir d'un coup les 20 derniers tweets du mec.
SILENCE_PREMIER_RUN = _bool("SILENCE_PREMIER_RUN", True)


def verifier() -> list:
    """Les reglages manquants pour la combinaison choisie (vide = tout est bon).

    On ne reclame que les cles de la source et du fournisseur actifs : exiger
    une cle Anthropic quand on tourne en Gemini gratuit n'aurait aucun sens.
    """
    manques = []
    if not HANDLES:
        manques.append("X_HANDLES (le ou les comptes a suivre, sans @)")

    if SOURCE_X in ("telegram", "auto"):
        if not TELEGRAM_CANAL:
            manques.append("TELEGRAM_CANAL (source X = " + SOURCE_X + ")")
    elif SOURCE_X == "syndication":
        pass
    elif SOURCE_X == "apify":
        if not APIFY_TOKEN:
            manques.append("APIFY_TOKEN (source X = apify)")
    else:
        if not TWITTERAPI_KEY:
            manques.append("TWITTERAPI_IO_KEY (source X = twitterapi)")

    if FOURNISSEUR_IA == "anthropic":
        if not ANTHROPIC_API_KEY:
            manques.append("ANTHROPIC_API_KEY (IA = anthropic)")
    else:
        if not GEMINI_API_KEY:
            manques.append("GEMINI_API_KEY (IA = gemini)")

    if not TELEGRAM_BOT_TOKEN:
        manques.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        manques.append("TELEGRAM_CHAT_ID")
    return manques
