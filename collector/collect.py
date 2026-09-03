#!/usr/bin/env python3
"""Radar Mini — collecte, score, notifie.

Usage :
    python collector/collect.py            # collecte complete
    python collector/collect.py --dry-run  # sans notification
    python collector/collect.py --fixture  # test hors ligne sur un jeu d'essai
"""

import argparse
import json
import os
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent))

# la console Windows est en cp1252 : sans ca, les fleches et accents plantent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402
import score as scoring  # noqa: E402
import sources  # noqa: E402

RACINE = pathlib.Path(__file__).resolve().parent.parent
FICHIER = RACINE / "data" / "annonces.json"
CONFIG = RACINE / "config.json"


def maintenant():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def age_en_jours(horodatage: str) -> float:
    try:
        d = datetime.fromisoformat(horodatage)
    except (TypeError, ValueError):
        return 0.0
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - d).total_seconds() / 86400


def charger_existant():
    if FICHIER.exists():
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    return {"genere_le": None, "sources": {}, "annonces": []}


def collecter(cfg, fixture=False, detail=False, seule=None):
    if fixture:
        chemin = RACINE / "collector" / "fixture.json"
        return json.loads(chemin.read_text(encoding="utf-8")), {"fixture": "ok"}

    actives = cfg.get("sources", {})
    brutes, etat = [], {}
    for nom, fn in sources.TOUTES.items():
        if seule and nom.lower() != seule.lower():
            continue
        if not seule and not actives.get(nom, True):
            etat[nom] = "desactivee"
            print(f"→ {nom} : desactivee dans config.json")
            continue
        print(f"→ {nom}")
        try:
            res = fn()
            brutes += res
            etat[nom] = f"ok ({len(res)})"
            print(f"  {len(res)} annonces")
            if detail:
                for a in res[:8]:
                    print(f"    {a['prix'] or '?':>7} € · {a.get('annee') or '?'} · "
                          f"{a['pays'][:12]:<12} · {a['titre'][:58]}")
        except Exception as e:
            etat[nom] = f"erreur : {e}"
            print(f"  ! {e}")
    return brutes, etat


def notifier(cfg, pepites):
    topic = cfg["notifications"]["ntfy_topic"]
    if not topic or "CHANGEMOI" in topic:
        print("! topic ntfy non configure : pas de notification envoyee")
        return
    for a in pepites[:5]:  # jamais plus de 5 push d'un coup
        prix = f"{a['prix']} €" if a["prix"] else "prix nc"
        corps = (f"{prix} · {a.get('annee') or '?'} · {a['pays']}\n"
                 f"{a['titre'][:110]}\n"
                 f"Score {a['score']}/100 · rouille : {a['risque_rouille']}")
        try:
            requests.post(
                f"https://ntfy.sh/{topic}",
                data=corps.encode("utf-8"),
                headers={
                    "Title": f"Pepite Mini {a['score']}/100 — {prix}".encode("utf-8"),
                    "Priority": "high" if a["score"] >= 85 else "default",
                    "Tags": "car",
                    "Click": a["url"],
                },
                timeout=15,
            )
            print(f"  push envoye : {a['titre'][:50]}")
        except Exception as e:
            print(f"  ! push echoue : {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fixture", action="store_true")
    ap.add_argument("--detail", action="store_true",
                    help="affiche un echantillon de ce que remonte chaque source")
    ap.add_argument("--source", metavar="NOM",
                    help="ne lance qu'une source, meme si elle est desactivee")
    args = ap.parse_args()

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    if os.getenv("NTFY_TOPIC"):
        cfg["notifications"]["ntfy_topic"] = os.environ["NTFY_TOPIC"]

    # le jeu d'essai ne doit jamais se melanger aux vraies annonces : il ne lit
    # ni n'ecrit data/annonces.json, il affiche seulement son classement.
    connus = {} if args.fixture else {a["id"]: a for a in charger_existant().get("annonces", [])}

    brutes, etat = collecter(cfg, fixture=args.fixture,
                             detail=args.detail, seule=args.source)
    print(f"\n{len(brutes)} annonces brutes")

    # Si tout est tombe alors qu'on avait des annonces, c'est le collecteur qui
    # a un probleme, pas le marche qui s'est vide : on ne touche a rien.
    # Le cas est realiste — les protections anti-robot repondent 403 selon l'IP
    # d'ou part la requete, et celle d'un runner GitHub n'est pas la tienne.
    if not brutes and connus and not args.fixture:
        print("! aucune source n'a repondu : data/annonces.json laisse intact")
        return

    vues, retenues, nouvelles = set(), [], []
    for a in brutes:
        if a["id"] in vues:
            continue
        vues.add(a["id"])
        if scoring.exclure(a, cfg):
            continue
        a = scoring.scorer(a, cfg)
        if a["id"] in connus:
            a["vue_le"] = connus[a["id"]].get("vue_le", maintenant())
            a["nouvelle"] = False
            ancien_prix = connus[a["id"]].get("prix", 0)
            if ancien_prix and a["prix"] and a["prix"] < ancien_prix:
                a["baisse_prix"] = ancien_prix - a["prix"]
        else:
            a["vue_le"] = maintenant()
            a["nouvelle"] = True
            nouvelles.append(a)
        retenues.append(a)

    # On garde les annonces disparues quelques jours, marquees, puis on les
    # oublie. Sans cette purge le fichier ne fait que grossir.
    #
    # Mais on ne declare disparue qu'une annonce dont la source a repondu. Une
    # source tombee ne prouve rien sur ses annonces : quand leParking renvoyait
    # 403 depuis le runner GitHub, ses 69 annonces se faisaient marquer
    # "retiree" a chaque passage alors qu'elles etaient bien en ligne — le site
    # affichait un cimetiere. Sans nouvelle d'une source, on ne touche pas a
    # ses annonces, ni au drapeau ni au compteur de retention.
    jours = cfg.get("retention", {}).get("jours_apres_disparition", 10)
    ids_actifs = {a["id"] for a in retenues}
    vivantes = {nom for nom, e in etat.items() if e.startswith("ok")}
    for id_, a in connus.items():
        if id_ in ids_actifs:
            continue
        if a.get("source") not in vivantes:
            retenues.append(a)          # source muette : on garde en l'etat
            continue
        a["disparue"] = True
        a.setdefault("disparue_le", maintenant())
        if age_en_jours(a["disparue_le"]) <= jours:
            retenues.append(a)

    retenues.sort(key=lambda a: (-a.get("score", 0), a.get("prix") or 99999))

    seuil = cfg["notifications"]["score_minimum"]
    plafond = cfg["notifications"]["toujours_notifier_si_prix_max"]
    pepites = [a for a in nouvelles
               if a["score"] >= seuil
               or (a["prix"] and a["prix"] <= plafond and a["score"] >= 55)]

    print(f"{len(retenues)} annonces retenues · {len(nouvelles)} nouvelles · "
          f"{len(pepites)} pepites")

    if args.fixture:
        print("\nclassement du jeu d'essai :")
        for a in retenues:
            print(f"  {a['score']:3} · {a['prix'] or '?':>6} € · {a['pays']:<8} · "
                  f"rouille {a['risque_rouille']:<12} · {a['titre'][:44]}")
        return

    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    FICHIER.write_text(json.dumps({
        "genere_le": maintenant(),
        "sources": etat,
        "budget": cfg["budget"],
        # Le site laisse regler le budget dans le navigateur et chiffre le
        # rapatriement des annonces etrangeres : il lui faut ces baremes, il ne
        # lit que ce fichier.
        "import": cfg.get("import", {}),
        "stats": {
            "total": len(retenues),
            "nouvelles": len(nouvelles),
            "pepites": len(pepites),
            "sous_2k": len([a for a in retenues
                            if 0 < (a.get("prix") or 0) <= cfg["budget"]["achat_immediat"]]),
        },
        "annonces": retenues,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    if pepites and not args.dry_run:
        notifier(cfg, pepites)


if __name__ == "__main__":
    main()
