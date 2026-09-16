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


def _float(nom: str, defaut: float) -> float:
    try:
        return float(os.getenv(nom, "").strip().replace(",", "."))
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
# Apify est facture au tweet ramene (~0,008 $ par passage de 5, mesure le
# 12/09/2026). Les 5 $ offerts chaque mois ne couvrent donc qu'environ un
# passage par heure. On l'espace, pendant que Telegram assure la reactivite.
# Espacement MINIMAL entre deux appels Apify, meme quand le compteur dit
# qu'il a publie. Garde-fou : si la detection deraille, les credits ne
# partent pas en une nuit.
APIFY_MIN_ENTRE_APPELS = _int("APIFY_MIN_ENTRE_APPELS", 4)

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

# ── Affichage ─────────────────────────────────────────────
# Fuseau des dates dans les alertes. Les sources datent toutes en UTC ;
# sans conversion, un post de 23h08 a Paris s'affichait "21h08".
# Nom IANA ("Europe/Paris", "America/New_York"...), pas un decalage fixe :
# l'heure d'ete doit suivre toute seule.
FUSEAU = os.getenv("FUSEAU", "Europe/Paris").strip() or "Europe/Paris"

# ── Republications ────────────────────────────────────────
# Le compte supprime et republie son post dans les minutes qui suivent,
# souvent pour corriger un chiffre ou ajouter un TP. Deux tweets, deux
# images re-televersees : rien ne les relie techniquement, sauf le trade
# qu'ils decrivent. Quand la meme paire, le meme sens et le meme prix
# d'entree reviennent dans cette fenetre, on MODIFIE l'alerte deja publiee
# au lieu d'en envoyer une seconde.
# Mesure du 16/09/2026 : 4 minutes entre la suppression et la republication.
ANTI_REPOST_MIN = _float("ANTI_REPOST_MIN", 15.0)
# Ecart de prix tolere entre les deux annonces (76 332,34 vs 76 332).
ANTI_REPOST_TOLERANCE_PCT = _float("ANTI_REPOST_TOLERANCE_PCT", 0.1)

# ── Le stop ───────────────────────────────────────────────
# Il est affiche en priorite tel qu'il est lu (texte ou boite TradingView).
# Quand il n'est pas lisible, on le DEDUIT de l'entree, et l'alerte le
# marque comme estime pour qu'on ne le confonde jamais avec un stop annonce.
#
# 0,9 % vient de la mesure de 10 entrees datees d'@astronomer_zero (juillet
# a septembre 2026), stops relevés sur l'outil de position TradingView :
#   0,15 · 0,43 · 0,45 · 0,54 · 0,56 · 0,73 · 0,81 · 0,82 · 1,18 · 2,13 %
# Moyenne 0,78 %, mediane 0,65 %. A 0,90 % on couvre 8 de ces 10 trades ;
# monter a 1,20 % en couvre un de plus pour un tiers de risque en plus.
# C'est le point d'inflexion, donc le defaut.
#
# Son trade POSITIONNEL (long journalier du 21/08) tenait un stop a 5,77 % :
# une estimation a 0,9 % n'a de sens que sur ses entrees intraday et swing,
# qui sont la quasi-totalite de ce qu'il publie.
STOP_ESTIME = _bool("STOP_ESTIME", True)
STOP_ESTIME_PCT = _float("STOP_ESTIME_PCT", 0.9)

# Au-dela de cet ecart, un stop lu sur une image ne decrit plus l'entree du
# jour : c'est presque toujours une boite qui raconte un trade anterieur.
# On le jette et on estime a la place, plutot que d'afficher un chiffre faux.
STOP_ECART_MAX_PCT = _float("STOP_ECART_MAX_PCT", 8.0)

# GARDE-FOU D'AGE — le plus important du programme.
# Le timeline X remonte un an d'historique. Des qu'une source revient apres
# une absence, ou que la memoire est perdue, des dizaines de vieux posts
# deviennent "nouveaux" et partent en alertes. Un post plus vieux que cette
# limite n'est JAMAIS alerte, quoi que dise la memoire : une alerte porte
# sur un trade qu'on peut encore prendre, pas sur un tweet d'octobre dernier.
AGE_MAX_HEURES = _int("AGE_MAX_HEURES", 6)

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
