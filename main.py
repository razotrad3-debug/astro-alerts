"""
x-short-watcher — surveille un compte X, lit les captures qu'il poste,
et previent sur Telegram ou il a shorte (ou longe).

Usage :
    python main.py                 un passage, puis on sort (mode cron/Actions)
    python main.py --boucle        tourne en continu, un passage par minute
    python main.py --test          diagnostic : cles, API, dernier tweet
    python main.py --rejouer 3     re-analyse les 3 derniers tweets et envoie
"""
import argparse
import sys
import time
import traceback

# La console Windows est en cp1252 par defaut : afficher un message contenant
# des emoji y leve UnicodeEncodeError et tue le run. On force l'UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import config
from watcher import etat as memoire
from watcher import message, source, telegram, vision


# Mots qui peuvent signaler un trade. Sert uniquement a eviter d'appeler
# l'IA pour rien — la decision finale reste la sienne.
_MOTS_TRADE = (
    "short", "long", "buy", "sell", "entry", "entree", "tp", "sl", "stop",
    "target", "position", "flip", "closed", "close", "cloture", "profit",
    "pnl", "btc", "eth", "sol", "trade", "scalp", "leverage", "liquid",
    "$", "%", "k ", "support", "resistance", "bounce", "pump", "dump",
)


def _merite_analyse(tweet: dict) -> bool:
    """Ce message peut-il contenir un trade ?

    La chaine Telegram est pleine de messages d'ambiance ("Well well well...",
    "Good morning, dear friends") qui ne contiennent aucun trade possible.
    Les envoyer a l'IA gaspille le quota gratuit sans jamais produire
    d'alerte. Le filtre est volontairement large : au moindre doute on
    analyse, car rater un setup coute plus cher qu'un appel inutile.
    """
    if tweet.get("images"):
        return True
    texte = (tweet.get("texte") or "").strip()
    if len(texte) >= 120:
        return True
    bas = texte.lower()
    if any(c.isdigit() for c in bas):
        return True
    return any(m in bas for m in _MOTS_TRADE)


def _traiter_tweet(tweet: dict) -> bool:
    """Analyse un tweet et envoie l'alerte si elle a lieu d'etre."""
    if not tweet.get("images") and not config.ANALYSER_SANS_IMAGE:
        print("   (pas d'image, ignore)")
        return False

    if not _merite_analyse(tweet):
        print("   (message d'ambiance, pas d'appel a l'IA)")
        return False

    analyse = vision.analyser(tweet)

    if analyse.get("erreur"):
        print("   erreur analyse : " + str(analyse["erreur"]))
    else:
        print("   -> " + str(analyse.get("ticker")) + " "
              + str(analyse.get("sens")) + " / statut "
              + str(analyse.get("statut"))
              + " / confiance " + str(analyse.get("confiance")))

    statut = (analyse.get("statut") or "inconnu").lower()
    interessant = statut in config.STATUTS_ALERTE or bool(analyse.get("erreur"))
    if not interessant and not config.ALERTER_SANS_TRADE:
        print("   (statut " + statut + ", pas une entree -> pas d'alerte)")
        return False

    texte = message.construire(tweet, analyse)
    images = tweet.get("images") or []
    if images:
        ok = telegram.envoyer_photo(images[0], texte)
    else:
        ok = telegram.envoyer(texte)
    print("   alerte envoyee" if ok else "   ECHEC envoi Telegram")
    return ok


def passage() -> None:
    """Un tour complet sur tous les comptes suivis."""
    etat = memoire.charger()

    for handle in config.HANDLES:
        print("[" + handle + "] lecture du timeline...")
        try:
            tweets = source.derniers_tweets(handle)
        except source.ErreurSource as e:
            print("   " + str(e))
            continue
        except Exception as e:
            print("   erreur inattendue : " + str(e))
            continue

        print("   " + str(len(tweets)) + " tweet(s) retenu(s)")

        premier = memoire.est_premier_run(etat, handle)
        vus = memoire.deja_vus(etat, handle)
        nouveaux = [t for t in tweets if t["id"] not in vus]

        if premier and config.SILENCE_PREMIER_RUN:
            # Premier demarrage : on enregistre l'existant sans alerter,
            # sinon on recoit d'un coup tout l'historique disponible.
            memoire.marquer(etat, handle, [t["id"] for t in tweets])
            print("   premier run : " + str(len(tweets))
                  + " tweet(s) marques comme vus, aucune alerte envoyee")
            continue

        if not nouveaux:
            print("   rien de nouveau")
            memoire.marquer(etat, handle, [])
            continue

        for i, t in enumerate(nouveaux):
            # Le palier gratuit de Gemini plafonne par minute : on espace
            # les analyses quand plusieurs messages arrivent ensemble.
            if i:
                time.sleep(6)
            print("   nouveau tweet " + t["id"] + " (" + str(len(t["images"])) + " image(s))")
            try:
                _traiter_tweet(t)
            except Exception:
                traceback.print_exc()
            # Marque meme en cas d'echec : un tweet illisible ne doit pas
            # bloquer la file a chaque passage du cron.
            memoire.marquer(etat, handle, [t["id"]])

    memoire.sauver(etat)


def diagnostic() -> int:
    print("=== Diagnostic x-short-watcher ===")
    manques = config.verifier()
    if manques:
        print("Reglages manquants :")
        for m in manques:
            print("  - " + m)
        return 1
    print("Cles : OK")
    print("Comptes suivis : " + ", ".join("@" + h for h in config.HANDLES))
    print("Source X : " + source.nom())
    modele = config.MODELE if config.FOURNISSEUR_IA == "anthropic" else config.GEMINI_MODELE
    print("IA : " + config.FOURNISSEUR_IA + " (" + modele + ")")

    handle = config.HANDLES[0]
    print("\nAppel " + source.nom() + " sur @" + handle + "...")
    try:
        tweets, brut = source.derniers_tweets(handle, brut_aussi=True)
    except Exception as e:
        print("ECHEC : " + str(e))
        return 1
    if not tweets:
        print("Aucun tweet exploitable. Cles du JSON recu : "
              + str(list(brut.keys()) if isinstance(brut, dict) else type(brut)))
        print("Si le compte poste bien, ajuste APIFY_ACTEUR ou TWITTERAPI_IO_PATH dans le .env.")
        return 1
    dernier = tweets[-1]
    print("OK — dernier tweet " + dernier["id"] + " : "
          + (dernier["texte"][:100] or "(sans texte)"))
    print("Images detectees : " + str(len(dernier["images"])))
    for u in dernier["images"]:
        print("   " + u)

    print("\nAnalyse de ce tweet par " + config.FOURNISSEUR_IA + "...")
    analyse = vision.analyser(dernier)
    for cle, val in analyse.items():
        print("   " + cle + " = " + str(val))

    print("\nEnvoi d'un message de test sur Telegram...")
    ok = telegram.envoyer(message.construire(dernier, analyse))
    print("Telegram : " + ("OK" if ok else "ECHEC"))
    return 0 if ok else 1


def trouver_chat_id() -> int:
    """Affiche le(s) chat_id qui ont ecrit au bot, pour remplir le .env.

    C'est l'etape ou tout le monde se plante : Telegram ne donne pas le
    chat_id dans son interface, il faut le lire dans getUpdates.
    """
    import requests

    if not config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN est vide dans le .env.")
        print("Parle a @BotFather sur Telegram -> /newbot -> colle le token.")
        return 1

    base = "https://api.telegram.org/bot" + config.TELEGRAM_BOT_TOKEN

    try:
        moi = requests.get(base + "/getMe", timeout=15).json()
    except Exception as e:
        print("Telegram injoignable : " + str(e))
        return 1
    if not moi.get("ok"):
        print("Token refuse par Telegram : " + str(moi.get("description")))
        return 1
    nom = moi["result"].get("username", "?")
    print("Bot reconnu : @" + nom)

    try:
        maj = requests.get(base + "/getUpdates", timeout=15).json()
    except Exception as e:
        print("Lecture des messages impossible : " + str(e))
        return 1

    vus = {}
    for u in maj.get("result", []):
        for cle in ("message", "channel_post", "edited_message", "my_chat_member"):
            chat = (u.get(cle) or {}).get("chat")
            if isinstance(chat, dict) and chat.get("id") is not None:
                vus[chat["id"]] = (chat.get("title")
                                   or chat.get("username")
                                   or chat.get("first_name")
                                   or chat.get("type") or "?")

    if not vus:
        print("")
        print("Aucun message recu pour l'instant.")
        print("Ouvre Telegram, cherche @" + nom + ", envoie-lui n'importe quoi")
        print("(par exemple /start), puis relance cette commande.")
        return 1

    print("")
    print("chat_id trouve(s) :")
    for cid, qui in vus.items():
        print("   TELEGRAM_CHAT_ID=" + str(cid) + "     (" + str(qui) + ")")
    print("")
    print("Copie la ligne qui te concerne dans le fichier .env.")
    return 0


def envoyer_dernieres_entrees(n: int) -> int:
    """Renvoie les n dernieres ENTREES du timeline, en ignorant la memoire.

    Sert a verifier le systeme sur du vrai contenu, ou a rattraper apres une
    interruption. Contrairement a --rejouer, on ne s'arrete pas aux N derniers
    messages : on remonte jusqu'a trouver N entrees, puisque la plupart des
    posts sont du suivi de position.
    """
    handle = config.HANDLES[0]
    try:
        messages = source.derniers_tweets(handle)
    except Exception as e:
        print("Lecture impossible : " + str(e))
        return 1

    print(str(len(messages)) + " message(s) disponibles, recherche des entrees...")

    retenus = []
    for t in reversed(messages):          # du plus recent au plus ancien
        if len(retenus) >= n:
            break
        if not t.get("images") and not config.ANALYSER_SANS_IMAGE:
            continue
        if not _merite_analyse(t):
            continue
        analyse = vision.analyser(t)
        if analyse.get("erreur"):
            print("   erreur : " + str(analyse["erreur"])[:70])
            continue
        statut = (analyse.get("statut") or "?").lower()
        print("   [" + statut + "] " + t["texte"][:55].replace("\n", " "))
        if statut in config.STATUTS_ALERTE:
            retenus.append((t, analyse))
        time.sleep(4)                     # palier gratuit : limite par minute

    # On envoie du plus ancien au plus recent, pour lire le fil dans l'ordre.
    envoyes = 0
    for t, analyse in reversed(retenus):
        texte = message.construire(t, analyse)
        images = t.get("images") or []
        ok = telegram.envoyer_photo(images[0], texte) if images else telegram.envoyer(texte)
        if ok:
            envoyes += 1
        print("   envoi " + str(envoyes) + "/" + str(len(retenus)) + " : "
              + str(analyse.get("ticker")) + " " + str(analyse.get("sens")))
        time.sleep(4)

    print(str(envoyes) + " entree(s) envoyee(s)")
    return 0


def rejouer(n: int) -> None:
    """Re-analyse les n derniers tweets et envoie, en ignorant la memoire."""
    for handle in config.HANDLES:
        tweets = source.derniers_tweets(handle)[-n:]
        print("[" + handle + "] rejeu de " + str(len(tweets)) + " tweet(s)")
        for t in tweets:
            print("   tweet " + t["id"])
            _traiter_tweet(t)


def main() -> int:
    ap = argparse.ArgumentParser(description="Surveille un compte X et alerte sur Telegram.")
    ap.add_argument("--boucle", action="store_true", help="tourne en continu")
    ap.add_argument("--intervalle", type=int, default=60, help="secondes entre deux passages (--boucle)")
    ap.add_argument("--test", action="store_true", help="diagnostic complet")
    ap.add_argument("--rejouer", type=int, metavar="N", help="re-analyse les N derniers tweets")
    ap.add_argument("--chatid", action="store_true", help="affiche ton TELEGRAM_CHAT_ID")
    ap.add_argument("--entrees", type=int, metavar="N",
                    help="renvoie les N dernieres ENTREES trouvees dans le timeline")
    args = ap.parse_args()

    # Avant le controle de configuration : c'est justement la commande qui
    # sert a completer une configuration incomplete.
    if args.chatid:
        return trouver_chat_id()

    manques = config.verifier()
    if manques:
        print("Configuration incomplete :")
        for m in manques:
            print("  - " + m)
        print("\nRemplis le fichier .env (voir .env.example) ou les Secrets GitHub.")
        return 1

    if args.test:
        return diagnostic()

    if args.entrees:
        return envoyer_dernieres_entrees(args.entrees)

    if args.rejouer:
        rejouer(args.rejouer)
        return 0

    if args.boucle:
        print("Boucle active, un passage toutes les " + str(args.intervalle) + "s. Ctrl+C pour arreter.")
        while True:
            try:
                passage()
            except KeyboardInterrupt:
                print("\nArret.")
                return 0
            except Exception:
                traceback.print_exc()
            time.sleep(args.intervalle)

    passage()
    return 0


if __name__ == "__main__":
    sys.exit(main())
