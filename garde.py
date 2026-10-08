"""
Garde-fou de la file GitHub Actions du watcher.

Historique :
  - 24/09/2026 : un passage reste en "queued" 22 h en tenant le verrou de
    concurrence ; 799 passages annules, trois jours sans alerte. D'ou ce garde.
  - 08/10/2026 : cinq passages "queued" depuis plus de 24 h, que GitHub
    refuse d'annuler (409, meme en force-cancel) et n'a pas purges. Mais ils
    ne bloquaient RIEN : le watcher reussissait toutes les 2 min a cote. Le
    garde criait pourtant "File debloquee... les alertes reprennent", deux
    fois, alors qu'il n'avait rien debloque et qu'il n'y avait rien a
    debloquer. Fausse alerte ET faux message.

D'ou la regle actuelle : le critere de panne, c'est l'ABSENCE DE SUCCES
recents du watcher — pas la presence de passages en file. Tant que le
watcher reussit, le garde nettoie en silence et ne previent personne.

Il previent sur Telegram, une fois par panne (puis un rappel toutes les 6 h) :
  - si aucun passage du watcher n'a reussi depuis SEUIL_PANNE_MIN ;
  - si le watcher tourne encore, mais plus via cron-job.org depuis
    SEUIL_MINUTEUR_MIN (le cron GitHub seul le ralentit a 15-20 min).
Et ses messages disent ce qui s'est reellement passe.

Pas de memoire propre : pour ne prevenir qu'une fois, il regarde quand le
garde a tourne pour la derniere fois. Si c'etait deja pendant la panne,
quelqu'un a deja prevenu.

    DRY_RUN=1 python garde.py     # lecture seule, rien n'est annule ni envoye
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

DEPOT = os.getenv("GITHUB_REPOSITORY", "razotrad3-debug/astro-alerts")
JETON = os.getenv("GITHUB_TOKEN", "")
FLUX = os.getenv("WORKFLOW_SURVEILLE", "watch.yml")
GARDE = os.getenv("WORKFLOW_GARDE", "garde.yml")
MOI = os.getenv("GITHUB_RUN_ID", "")
ESSAI = os.getenv("DRY_RUN", "") not in ("", "0", "false")

SEUIL_PANNE_MIN = float(os.getenv("SEUIL_PANNE_MIN", "20"))
SEUIL_MINUTEUR_MIN = float(os.getenv("SEUIL_MINUTEUR_MIN", "30"))
SEUIL_FILE_MIN = float(os.getenv("SEUIL_FILE_MIN", "10"))
SEUIL_EXEC_MIN = float(os.getenv("SEUIL_EXEC_MIN", "15"))
RAPPEL_H = float(os.getenv("RAPPEL_H", "6"))

_EN_ATTENTE = ("queued", "pending", "waiting", "requested", "in_progress")


def _maintenant():
    return datetime.now(timezone.utc)


def _date(iso: str):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _api(methode: str, chemin: str):
    requete = urllib.request.Request(
        "https://api.github.com/repos/" + DEPOT + chemin, method=methode,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "astro-alerts-garde",
                 **({"Authorization": "Bearer " + JETON} if JETON else {})})
    try:
        with urllib.request.urlopen(requete, timeout=20) as r:
            corps = r.read()
            return r.status, (json.loads(corps) if corps else {})
    except urllib.error.HTTPError as e:
        return e.code, {}


def _runs(flux: str, filtre: str = "", n: int = 1) -> list:
    code, d = _api("GET", "/actions/workflows/" + flux + "/runs?per_page="
                   + str(n) + filtre)
    return (d.get("workflow_runs") or []) if code == 200 else []


def _telegram(texte: str) -> None:
    jeton, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if ESSAI or not jeton or not chat:
        print("[telegram] (non envoye) " + texte.replace("\n", " | "))
        return
    donnees = json.dumps({"chat_id": chat, "text": texte, "parse_mode": "HTML",
                          "disable_web_page_preview": True}).encode()
    requete = urllib.request.Request(
        "https://api.telegram.org/bot" + jeton + "/sendMessage", data=donnees,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(requete, timeout=20)
    except Exception as e:
        print("[telegram] envoi impossible : " + str(e))


def _annuler(run_id: int) -> str:
    """Annule, puis force, puis supprime. Renvoie ce qui a marche, ou non."""
    if ESSAI:
        return "simule"
    base = "/actions/runs/" + str(run_id)
    code, _ = _api("POST", base + "/cancel")
    if code in (202, 204):
        return "annule"
    code, _ = _api("POST", base + "/force-cancel")
    if code in (202, 204):
        return "annule (force)"
    # Des passages fantomes resistent aux deux (409, constate le 08/10). La
    # suppression est le dernier recours : un passage qui n'a jamais tourne
    # n'a ni journal ni resultat a perdre.
    code, _ = _api("DELETE", base)
    if code in (202, 204):
        return "supprime"
    return "refuse (" + str(code) + ")"


def _nettoyer() -> list:
    """Retire les passages coinces. Renvoie [(id, statut, age_min, resultat)]."""
    fait = []
    for statut in _EN_ATTENTE:
        for run in _runs(FLUX, "&status=" + statut, 50):
            age = (_maintenant() - _date(run["created_at"])).total_seconds() / 60
            seuil = SEUIL_EXEC_MIN if run["status"] == "in_progress" else SEUIL_FILE_MIN
            if age >= seuil:
                res = _annuler(run["id"])
                print("[garde] passage %s %s depuis %.0f min : %s"
                      % (run["id"], run["status"], age, res))
                fait.append((run["id"], run["status"], age, res))
    return fait


def _deja_prevenu(debut_panne) -> bool:
    """Un garde a-t-il deja tourne depuis le debut de la panne ?

    Si oui, il a prevenu. On ne relance que tous les RAPPEL_H heures.
    """
    for run in _runs(GARDE, "&status=completed", 20):
        if str(run["id"]) == MOI or run.get("conclusion") != "success":
            continue
        precedent = _date(run["created_at"])
        if precedent < debut_panne:
            return False
        tranche = lambda t: int((t - debut_panne) / timedelta(hours=RAPPEL_H))
        return tranche(precedent) == tranche(_maintenant())
    return False


def _age(run) -> float:
    return (_maintenant() - _date(run["created_at"])).total_seconds() / 60


def main() -> int:
    print("[garde] depot " + DEPOT + (" — MODE ESSAI" if ESSAI else ""))

    succes = _runs(FLUX, "&status=success")
    via_minuteur = _runs(FLUX, "&status=success&event=repository_dispatch")
    if not succes:
        print("[garde] aucun succes connu, rien a comparer")
        return 0
    age = _age(succes[0])
    age_min = _age(via_minuteur[0]) if via_minuteur else None
    print("[garde] dernier succes il y a %.0f min, via cron-job.org il y a %s min"
          % (age, "?" if age_min is None else "%.0f" % age_min))

    # ── Le watcher tourne : rien a signaler. On nettoie quand meme en
    # silence ce qui traine en file, sans jamais te deranger pour ca.
    if age < SEUIL_PANNE_MIN:
        fantomes = _nettoyer()
        if fantomes:
            print("[garde] %d passage(s) en file nettoye(s) sans alerte : "
                  "le watcher reussit, ils ne bloquaient rien" % len(fantomes))
        if age_min is not None and age_min >= SEUIL_MINUTEUR_MIN:
            debut = _date(via_minuteur[0]["created_at"]) + timedelta(minutes=SEUIL_MINUTEUR_MIN)
            if not _deja_prevenu(debut):
                _telegram("🟠 <b>Minuteur externe muet</b>\n\ncron-job.org n'a rien "
                          "declenche depuis %.0f min. Le bot tourne encore via le cron "
                          "GitHub, mais avec 15 a 20 min de retard." % age_min)
        return 0

    # ── Panne reelle : plus aucun succes depuis SEUIL_PANNE_MIN.
    fait = _nettoyer()
    debut = _date(succes[0]["created_at"]) + timedelta(minutes=SEUIL_PANNE_MIN)
    if _deja_prevenu(debut):
        print("[garde] panne deja signalee, pas de nouveau message")
        return 0

    lignes = ["🔴 <b>Astro Alerts bloque</b>",
              "", "Aucun passage reussi depuis %.0f min : les alertes ne partent pas." % age]
    reussis = [f for f in fait if f[3].startswith(("annule", "supprime"))]
    rates = [f for f in fait if f not in reussis]
    if reussis:
        lignes += ["", "J'ai retire %d passage(s) coince(s) de la file. Les alertes "
                   "devraient reprendre au prochain declenchement." % len(reussis)]
    if rates:
        lignes += ["", "%d passage(s) coince(s) resistent a l'annulation (GitHub "
                   "refuse)." % len(rates)]
    if not fait:
        lignes += ["", "Rien n'est coince dans la file : la cause est ailleurs "
                   "(minuteur, GitHub, source)."]
    _telegram("\n".join(lignes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
