"""
Garde-fou de la file GitHub Actions du watcher.

Ce qui s'est passe le 24/09/2026 : un passage est reste en "queued" 22 h
sans jamais recevoir de machine. Il tenait le verrou de concurrence, donc
chaque passage suivant s'est mis en file derriere lui puis a ete annule par
le suivant. 799 passages annules, trois jours sans alerte, et rien ne l'a
signale.

Ce script tourne dans un workflow SEPARE (garde.yml), avec son propre groupe
de concurrence : il ne peut donc pas etre bloque par le passage coince qu'il
est charge de debloquer. Il :

  1. annule tout passage du watcher en file depuis plus de SEUIL_FILE_MIN,
     ou en cours depuis plus de SEUIL_EXEC_MIN (un passage normal dure ~1 min) ;
  2. previent sur Telegram quand il a du intervenir ;
  3. previent si plus aucun passage n'a reussi depuis 45 min, ou si le
     minuteur externe (cron-job.org) ne declenche plus rien.

Bibliotheque standard uniquement : pas de pip install, le garde demarre en
quelques secondes.

    DRY_RUN=1 python garde.py     # lecture seule, rien n'est annule ni envoye
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEPOT = os.getenv("GITHUB_REPOSITORY", "razotrad3-debug/astro-alerts")
JETON = os.getenv("GITHUB_TOKEN", "")
FLUX = os.getenv("WORKFLOW_SURVEILLE", "watch.yml")
ESSAI = os.getenv("DRY_RUN", "") not in ("", "0", "false")

SEUIL_FILE_MIN = float(os.getenv("SEUIL_FILE_MIN", "10"))
SEUIL_EXEC_MIN = float(os.getenv("SEUIL_EXEC_MIN", "15"))

# Fenetres d'alerte. Le garde n'a pas de memoire : pour ne pas envoyer un
# message a chaque passage pendant une longue panne, on ne previent que tant
# que le silence est dans une fenetre bornee. Elle est assez large (90 min)
# pour qu'au moins un passage du garde y tombe, meme quand GitHub retarde
# ses crons de 20 ou 30 minutes.
SILENCE_TOTAL = (45, 135)     # plus aucun passage reussi, toutes sources
SILENCE_EXTERNE = (30, 120)   # plus aucun declenchement de cron-job.org

_EN_ATTENTE = ("queued", "pending", "waiting", "requested", "in_progress")


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


def _age_min(iso: str) -> float:
    d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - d).total_seconds() / 60.0


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
    """Annule un passage ; force l'annulation si GitHub refuse la normale."""
    if ESSAI:
        return "simule"
    code, _ = _api("POST", "/actions/runs/" + str(run_id) + "/cancel")
    if code in (202, 204):
        return "annule"
    # 409 : GitHub n'arrive pas a l'annuler proprement, typiquement un
    # passage coince sans machine. force-cancel existe precisement pour ca.
    code, _ = _api("POST", "/actions/runs/" + str(run_id) + "/force-cancel")
    return "force" if code in (202, 204) else "echec (" + str(code) + ")"


def debloquer() -> list:
    """Annule les passages coinces. Renvoie ce qui a ete fait."""
    fait = []
    for statut in _EN_ATTENTE:
        code, d = _api("GET", "/actions/workflows/" + FLUX
                       + "/runs?status=" + statut + "&per_page=50")
        if code != 200:
            print("[garde] liste " + statut + " : HTTP " + str(code))
            continue
        for run in d.get("workflow_runs") or []:
            age = _age_min(run["created_at"])
            seuil = SEUIL_EXEC_MIN if run["status"] == "in_progress" else SEUIL_FILE_MIN
            if age < seuil:
                continue
            resultat = _annuler(run["id"])
            print("[garde] passage %s %s depuis %.0f min : %s"
                  % (run["id"], run["status"], age, resultat))
            fait.append((run["id"], run["status"], age, resultat))
    return fait


def _dernier_succes(filtre: str = ""):
    code, d = _api("GET", "/actions/workflows/" + FLUX
                   + "/runs?status=success&per_page=1" + filtre)
    runs = (d.get("workflow_runs") or []) if code == 200 else []
    return _age_min(runs[0]["created_at"]) if runs else None


def main() -> int:
    print("[garde] depot " + DEPOT + ", flux " + FLUX
          + (" — MODE ESSAI, rien n'est modifie" if ESSAI else ""))

    fait = debloquer()
    if fait:
        lignes = ["⚠️ <b>File GitHub debloquee automatiquement</b>", ""]
        for rid, statut, age, res in fait:
            lignes.append("Passage %s, %s depuis %.0f min : %s" % (rid, statut, age, res))
        lignes += ["", "Les alertes reprennent au prochain declenchement."]
        _telegram("\n".join(lignes))
    else:
        print("[garde] aucun passage coince")

    total = _dernier_succes()
    externe = _dernier_succes("&event=repository_dispatch")
    print("[garde] dernier succes : %s min | dernier succes via cron-job.org : %s min"
          % (None if total is None else round(total),
             None if externe is None else round(externe)))

    if total is not None and SILENCE_TOTAL[0] <= total <= SILENCE_TOTAL[1]:
        _telegram("🔴 <b>Astro Alerts ne tourne plus</b>\n\nAucun passage reussi depuis "
                  "%.0f min. Les alertes ne partent pas." % total)
    elif externe is not None and SILENCE_EXTERNE[0] <= externe <= SILENCE_EXTERNE[1]:
        _telegram("🟠 <b>Minuteur externe muet</b>\n\ncron-job.org n'a rien declenche "
                  "depuis %.0f min. Le bot tourne encore via le cron GitHub, mais avec "
                  "15 a 20 min de retard." % externe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
