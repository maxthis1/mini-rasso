"""Scoring des annonces Mini classique.

Le score repond a une seule question : "est-ce que je dois y aller ce soir ?"
Il combine trois choses : le prix face a la cote de l'etat estime,
l'etat mecanique/carrosserie devine dans le texte, et le risque rouille.
"""

import re
import unicodedata

# Cote de reference marche France 2026 (mediane observee, Austin/Rover Mini
# classique 1959-2000, hors Cooper Mk1 et series rares).
COTE = {
    "epave": 900,        # non roulante, coque a refaire, pour pieces
    "projet": 2600,      # roulante ou presque, travaux tolerie a prevoir
    "projet_sain": 4800, # roulante, saine, cosmetique + entretien a faire
    "bon_etat": 9500,    # roule bien, CT ok, quelques defauts
    "tres_bon": 16000,   # restauree recente, dossier complet
}


def norm(txt: str) -> str:
    """Minuscules sans accents, pour matcher les mots-cles de facon fiable."""
    if not txt:
        return ""
    txt = unicodedata.normalize("NFD", txt.lower())
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 /]+", " ", txt)


def classe_etat(texte: str) -> str:
    """Devine la classe d'etat a partir du texte de l'annonce."""
    t = norm(texte)
    if any(k in t for k in ("epave", "pour pieces", "en pieces detachees",
                            "sans moteur", "coque a refaire", "chassis perce")):
        return "epave"
    if any(k in t for k in ("ne demarre pas", "ne roule pas", "non roulant",
                            "a restaurer entierement", "restauration totale a prevoir",
                            "planchers perces", "moteur hs")):
        return "projet"
    if any(k in t for k in ("restauration complete", "entierement restauree",
                            "coque neuve", "chassis neuf", "restauree en")):
        return "tres_bon"
    if any(k in t for k in ("ct ok", "ct vierge", "controle technique ok",
                            "roule parfaitement", "excellent etat", "tres bon etat")):
        return "bon_etat"
    if any(k in t for k in ("a restaurer", "projet", "travaux a prevoir",
                            "quelques travaux", "a finir", "rouille")):
        return "projet_sain"
    return "bon_etat"  # defaut prudent : on ne survalorise pas


# "aucune corrosion", "pas de rouille", "traitement anticorrosion" ne doivent
# jamais compter comme un defaut.
NEGATIONS = ("aucun", "aucune", "pas de", "sans", "zero", "jamais de",
             "anti", "traitement", "aucune trace de", "ni ", "exempte de",
             "exempt de", "aucun point de")


def _nie(t: str, position: int) -> bool:
    fenetre = t[max(0, position - 30):position]
    return any(n in fenetre for n in NEGATIONS)


def _mots(texte: str, table: dict, negation_annule=False) -> tuple[int, list]:
    t = norm(texte)
    total, touches = 0, []
    for mot, poids in table.items():
        pos = t.find(mot)
        if pos == -1:
            continue
        if negation_annule and _nie(t, pos):
            # le mot apparait, mais nie : on cherche une autre occurrence
            autre = t.find(mot, pos + 1)
            while autre != -1 and _nie(t, autre):
                autre = t.find(mot, autre + 1)
            if autre == -1:
                continue
        total += poids
        touches.append(mot)
    return total, touches


def scorer(annonce: dict, cfg: dict) -> dict:
    """Enrichit l'annonce avec score, etat, drapeaux. Renvoie l'annonce."""
    texte = f"{annonce.get('titre','')} {annonce.get('description','')}"
    mc = cfg["mots_cles"]
    budget = cfg["budget"]

    etat = classe_etat(texte)
    cote = COTE[etat]
    prix = annonce.get("prix") or 0

    # --- 1. Ecart a la cote (0-55 pts) ---------------------------------
    if prix <= 0:
        prix_pts = 20  # prix non communique : suspect mais pas eliminatoire
        ecart = None
    else:
        ecart = round((cote - prix) / cote * 100)  # +% = sous la cote
        prix_pts = max(0, min(55, 27 + ecart * 0.55))

    # --- 2. Mots-cles ---------------------------------------------------
    b_fort, t1 = _mots(texte, mc["bonus_fort"])
    b_leger, t2 = _mots(texte, mc["bonus_leger"])
    m_rouille, t3 = _mots(texte, mc["malus_rouille"], negation_annule=True)
    m_epave, t4 = _mots(texte, mc["malus_epave"], negation_annule=True)
    m_leger, t5 = _mots(texte, mc["malus_leger"])

    t_norm = norm(texte)
    if any(k in t_norm for k in ("aucune corrosion", "pas de rouille", "sans rouille",
                                 "aucune rouille", "aucune trace de rouille",
                                 "carrosserie saine", "coque saine")):
        b_fort += 12
        t1.append("carrosserie annoncee saine")
    bonus = min(32, b_fort + b_leger)
    malus = m_rouille + m_epave + m_leger

    # --- 3. Accessibilite budget ---------------------------------------
    if prix and prix <= budget["achat_immediat"]:
        budget_pts, tag_budget = 15, "achat immediat"
    elif prix and prix <= budget["budget_cible"]:
        budget_pts, tag_budget = 8, "a financer"
    elif prix and prix <= budget["plafond_absolu"]:
        budget_pts, tag_budget = 0, "hors budget court terme"
    else:
        budget_pts, tag_budget = -10, "hors budget"

    # --- 4. Pays --------------------------------------------------------
    coef = cfg["pays"].get(annonce.get("pays", "France"), 0.85)

    brut = prix_pts + bonus + malus + budget_pts
    score = max(0, min(100, round(brut * coef)))

    # --- Drapeaux lisibles ---------------------------------------------
    drapeaux = []
    if t3:
        drapeaux.append({"type": "rouille", "texte": "rouille annoncee : " + ", ".join(t3[:3])})
    if t4:
        drapeaux.append({"type": "epave", "texte": "signaux epave : " + ", ".join(t4[:3])})
    if "automatique" in norm(texte) or "bva" in norm(texte):
        drapeaux.append({"type": "info", "texte": "boite auto (AP suffix) : moins recherchee, pieces rares"})
    if any(k in norm(texte) for k in ("volant a droite", "rhd")):
        drapeaux.append({"type": "info", "texte": "volant a droite"})
    if t1:
        drapeaux.append({"type": "bon", "texte": ", ".join(t1[:3])})
    if not annonce.get("annee"):
        drapeaux.append({"type": "info", "texte": "annee non renseignee"})

    annonce.update({
        "score": score,
        "etat": etat,
        "cote_estimee": cote,
        "ecart_cote": ecart,
        "tag_budget": tag_budget,
        "drapeaux": drapeaux,
        "risque_rouille": "eleve" if m_rouille <= -30 else ("moyen" if m_rouille < 0 else "non annonce"),
    })
    return annonce


def exclure(annonce: dict, cfg: dict) -> bool:
    """True si l'annonce est du bruit (miniature, lot de pieces, hors periode)."""
    t = norm(f"{annonce.get('titre','')} {annonce.get('description','')}")
    for mot in cfg["exclusions"]["titres_interdits"]:
        if norm(mot) in t:
            return True
    for mot in cfg["exclusions"].get("modeles_modernes", []):
        if norm(mot) in t:
            return True
    annee = annonce.get("annee")
    if annee and not (cfg["recherche"]["annee_min"] <= annee <= cfg["recherche"]["annee_max"]):
        return True
    if not annee and cfg["recherche"].get("annee_obligatoire"):
        return True
    # leParking agrege aussi hors d'Europe : un pays absent de config.json
    # n'est pas un pays qu'on ira visiter.
    pays = annonce.get("pays")
    if pays and pays != "commentaire" and pays not in cfg["pays"]:
        return True
    prix = annonce.get("prix") or 0
    if prix > cfg["budget"]["plafond_absolu"]:
        return True
    if 0 < prix < 200:  # prix d'appel bidon / pieces
        return True
    return False
