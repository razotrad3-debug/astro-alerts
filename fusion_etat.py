"""
Reconcilie le state.json local avec celui pousse entre-temps par un autre
passage.

Appele par le workflow quand `git push` est refuse. Sans ca le rebase
echouait sur deux state.json divergents, le passage se terminait en erreur
et son ecriture etait perdue — donc une deuxieme alerte sur le meme tweet
au passage suivant.

    python fusion_etat.py state.json distant.json
"""
import json
import sys

from watcher import etat


def _lire(chemin: str) -> dict:
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception as e:
        print("[fusion] " + chemin + " illisible (" + str(e) + "), ignore.")
        return {}


def main(argv) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2

    local, distant = _lire(argv[1]), _lire(argv[2])
    sortie = etat.fusionner(local, distant)

    with open(argv[1], "w", encoding="utf-8") as f:
        json.dump(sortie, f, ensure_ascii=False, indent=2)

    for cle in sorted(k for k in sortie if not k.startswith("_")):
        print("[fusion] " + cle + " : "
              + str(len(sortie[cle].get("ids", []))) + " id(s), "
              + str(len(sortie[cle].get("empreintes", []))) + " empreinte(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
