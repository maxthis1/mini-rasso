"""Sources d'annonces.

Chaque fonction renvoie une liste de dicts normalises :
    {id, titre, description, prix, annee, km, lieu, pays, url, image, source}

Regle : une source qui tombe ne casse jamais la collecte. On log et on continue.
Le collecteur affiche l'etat de chaque source sur le site.

Etat des sources au 2 septembre 2026, verifie sur donnees reelles :

  leParking      OK   via le seul domaine leparking.be. Les autres domaines du
                      groupe (fr, es, it, pt, de, ch, theparking.eu) repondent
                      403 derriere un challenge JavaScript Cloudflare. Le .be
                      n'est pas un repli au rabais : le meta-moteur est le meme
                      et renvoie les annonces des sept pays.
  lesAnciennes   OK   annonces de collection FR, mais tarif marchand : la
                      quasi-totalite depasse le plafond de 7 000 €. Utile pour
                      calibrer la cote, pas pour trouver une affaire.
  ParuVendu      OK   via les pages SEO par marque. L'ancienne URL de recherche
                      renvoie 404 et le filtre par marque en parametre est
                      ignore par le serveur.
  eBay           HS   403 Akamai Bot Manager. Passer par l'API Browse officielle
                      (cle developpeur) est la seule voie propre.
  Car & Classic  HS   403 challenge Cloudflare, meme situation.

Les deux dernieres sont desactivees dans config.json. On ne cherche pas a
contourner une protection anti-robot : soit on passe par une API officielle,
soit on se passe de la source.
"""

import hashlib
import html
import json
import re
import time

import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}
TIMEOUT = 25
PAUSE = 1.5

# Ces sites separent les milliers par une espace ordinaire, insecable ou fine
# insecable, souvent les trois dans la meme page.
ESPACES = r"[\s  ]"
NOMBRE = r"(?:\d{1,3}(?:%s\d{3})+)" % ESPACES

# Un montant : soit des milliers bien groupes, soit 3 a 6 chiffres d'affilee.
# Ecrit ainsi pour ne pas avaler le compteur de photos qui precede le prix sur
# les cartes ParuVendu ("10 20 980 €" doit donner 20980, pas 1020980).
MONTANT = re.compile(r"(%s|\d{3,6})\s*(?:€|EUR)" % NOMBRE)

# Meme prudence pour le kilometrage. Un motif trop large collait la date de
# publication au compteur : "Publiee le 28/04/2026 84 000 km" donnait
# 2 684 000 km. On exige donc un nombre bien forme, et on plafonne : au-dela,
# c'est une erreur de lecture, pas une Mini.
KILOMETRAGE = re.compile(r"(%s|\d{1,6})\s*km" % NOMBRE, re.I)
KM_PLAFOND = 500_000

# Les noms de pays des blocs JSON-LD leParking sont en majuscules et sans
# accent ; on les ramene sur les cles de config.json.
PAYS_JSONLD = {
    "FRANCE": "France", "BELGIQUE": "Belgique", "ESPAGNE": "Espagne",
    "ITALIE": "Italie", "PORTUGAL": "Portugal", "ALLEMAGNE": "Allemagne",
    "SUISSE": "Suisse", "ROYAUME-UNI": "Royaume-Uni", "PAYS-BAS": "Pays-Bas",
    "LUXEMBOURG": "Luxembourg", "AUTRICHE": "Autriche",
}


def _id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def _prix(txt) -> int:
    if txt is None:
        return 0
    if isinstance(txt, (int, float)):
        return int(txt)
    m = re.sub(r"[^\d]", "", str(txt).split(",")[0])
    return int(m) if m.isdigit() else 0


def _montant(texte: str, dernier=False) -> int:
    """Extrait un prix d'un texte de carte. dernier=True pour lesAnciennes,
    ou le prix ferme la carte, apres une description tronquee."""
    trouves = MONTANT.findall(texte or "")
    if not trouves:
        return 0
    return _prix(trouves[-1] if dernier else trouves[0])


def _km_valeur(valeur) -> int:
    """Kilometrage deja isole, tel que le donne le JSON-LD leParking. Au-dela
    du plafond on renvoie 0 : mieux vaut ne rien afficher qu'un chiffre faux,
    que le site presenterait avec le meme aplomb qu'un vrai."""
    n = _prix(valeur)
    return n if 0 < n <= KM_PLAFOND else 0


def _km_texte(texte: str) -> int:
    """Kilometrage a retrouver dans le texte d'une carte."""
    m = KILOMETRAGE.search(texte or "")
    return _km_valeur(m.group(1)) if m else 0


def _annee(txt: str):
    if not txt:
        return None
    m = re.search(r"\b(19[5-9]\d|200[01])\b", str(txt))
    return int(m.group(1)) if m else None


def _propre(txt: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(txt or "")).strip()


def _get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    # plusieurs de ces sites declarent mal leur encodage : on decode nous-memes
    return r.content.decode(r.apparent_encoding or "utf-8", errors="replace")

# --------------------------------------------------------------------------
# 1. leParking : le gros morceau.
#    Meta-moteur agregeant ~960 sites (leboncoin, La Centrale, AutoScout24,
#    mobile.de, 2ememain, lesAnciennes...). Les annonces sont publiees en
#    JSON-LD schema.org dans la page, une par bloc <script>.
#
#    Deux pieges verifies sur donnees reelles :
#    - le JSON-LD contient des retours a la ligne bruts dans les valeurs, donc
#      json.loads echoue sans strict=False ;
#    - la pagination est en JavaScript, aucun parametre d'URL ne la pilote. On
#      compense avec le tri par prix croissant, qui met justement le bas de
#      gamme en premiere page — exactement le segment recherche.
# --------------------------------------------------------------------------


PARKING_BASE = "https://www.leparking.be/voiture-occasion/{}.html"
# pas de slug "mini" seul : c'est la page de la marque MINI de BMW, elle noie
# le classement sous des R50 et des Countryman a 600 €.
PARKING_SLUGS = ["austin-mini", "rover-mini", "morris-mini", "innocenti-mini"]
PARKING_TRIS = ["prix_croissant", "date"]


def _titre_depuis_url(url: str, marque_seule=False) -> str:
    """URL leParking : /voiture-occasion-detail/<marque-modele>/<titre>/<code>.html
    Le segment de titre porte le libelle vendeur, celui d'avant la marque."""
    bouts = [b for b in url.split("/") if b]
    i = -3 if marque_seule else -2
    if len(bouts) < abs(i):
        return ""
    return _propre(bouts[i].replace("-", " "))


# leParking recopie parfois du markup a la place du titre vendeur : on retombe
# alors sur la marque et le modele, qui eux sont toujours propres.
TITRE_CASSE = re.compile(r"(noscript|iframe|<|&lt;|&gt;|^null$)", re.I)


def _titre_leparking(desc: str, nom: str, url: str) -> str:
    # la description commence par le titre vendeur, puis "Année 1982 ..."
    tete = re.split(r"\bAnn[eé]e\b", desc, maxsplit=1)[0].strip()
    for candidat in (tete, _propre(nom), _titre_depuis_url(url)):
        if candidat and not TITRE_CASSE.search(candidat):
            return candidat
    return _titre_depuis_url(url, marque_seule=True) or "Mini"


def _parse_jsonld_vehicles(html: str, source: str) -> list:
    """Extrait les blocs schema.org Vehicle d'une page leParking."""
    out = []
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json")}):
        brut = tag.string or tag.get_text() or ""
        for obj in _iter_json_objects(brut):
            if obj.get("@type") != "Vehicle":
                continue
            offers = obj.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            url = offers.get("url") or obj.get("url") or ""
            if not url:
                continue

            desc = _propre(obj.get("description", ""))
            titre = _titre_leparking(desc, obj.get("name", ""), url)

            adresse = (offers.get("availableAtOrFrom") or {}).get("address") or {}
            pays_brut = _propre((adresse.get("addressCountry") or {}).get("name", "")).upper()
            lieu = " ".join(x for x in (_propre(adresse.get("addressRegion", "")),
                                        _propre(adresse.get("postalCode", ""))) if x)

            out.append({
                "id": _id(url),
                "titre": titre[:110],
                "description": desc[:600],
                "prix": _prix(offers.get("price")),
                "annee": _annee(obj.get("productionDate")) or _annee(desc),
                "km": _km_valeur((obj.get("mileageFromOdometer") or {}).get("value")),
                "lieu": lieu,
                "pays": PAYS_JSONLD.get(pays_brut, pays_brut.title() or "Inconnu"),
                "url": url,
                "image": obj.get("image") or "",
                "source": source,
            })
    return out


def _iter_json_objects(bloc: str):
    """Tolerant : strict=False accepte les retours a la ligne bruts que
    leParking laisse dans ses chaines. Sinon on extrait objet par objet."""
    bloc = (bloc or "").strip()
    if not bloc:
        return
    try:
        data = json.loads(bloc, strict=False)
        if isinstance(data, list):
            yield from data
        else:
            yield data
        return
    except Exception:
        pass
    for m in re.finditer(r"\{(?:[^{}]|\{[^{}]*\})*\}", bloc, re.S):
        try:
            yield json.loads(m.group(0), strict=False)
        except Exception:
            continue


def _verdict(nom: str, res: list, erreurs: list, tentatives: int):
    """Une source dont toutes les requetes ont echoue n'est pas 'ok (0)', elle
    est morte. Sans ca le pied de site affiche un voyant vert sur une source
    qui ne remonte plus rien, et on ne s'en apercoit jamais."""
    if erreurs and len(erreurs) == tentatives:
        raise RuntimeError(f"{len(erreurs)}/{tentatives} requetes en echec — {erreurs[0]}")
    if erreurs:
        print(f"  ({len(erreurs)}/{tentatives} requetes en echec, {len(res)} annonces quand meme)")


def leparking() -> list:
    res, erreurs, tentatives = [], [], 0
    for slug in PARKING_SLUGS:
        for tri in PARKING_TRIS:
            url = f"{PARKING_BASE.format(slug)}?tri={tri}"
            tentatives += 1
            try:
                res += _parse_jsonld_vehicles(_get(url), "leParking")
            except Exception as e:
                erreurs.append(str(e))
                print(f"  ! leParking {slug}/{tri} : {e}")
            time.sleep(PAUSE)
    _verdict("leParking", res, erreurs, tentatives)
    return res

# --------------------------------------------------------------------------
# 2. lesAnciennes : specialiste collection FR.
#    Chaque annonce apparait dans deux <a> : un lien vendeur au texte inutile
#    ("Nimes 22") et la vraie carte. On regroupe par URL et on garde le plus
#    long — c'est ce qui distingue la carte du lien parasite.
#    Format de carte : <annee> <titre> Publiee le <date> <km> km <boite>
#    <carburant> <couleur> <description tronquee>... <prix> €
# --------------------------------------------------------------------------


ANCIENNES_URLS = [
    "https://www.lesanciennes.com/annonces/voiture-collection/mini-mini-austin/",
    "https://www.lesanciennes.com/annonces/voiture-collection/mini-cooper/",
]


def lesanciennes() -> list:
    out, erreurs = [], []
    for u in ANCIENNES_URLS:
        try:
            soup = BeautifulSoup(_get(u), "html.parser")
            cartes = {}
            for a in soup.select("a[href*='/annonce/']"):
                href = a["href"]
                texte = _propre(a.get_text(" ", strip=True))
                img = a.find("img")
                src = (img.get("src") or img.get("data-src") or "") if img else ""
                if len(texte) > len(cartes.get(href, ("", ""))[0]):
                    cartes[href] = (texte, src)

            for href, (texte, img) in cartes.items():
                if len(texte) < 40:  # lien vendeur isole, pas une carte
                    continue
                if href.startswith("/"):
                    href = "https://www.lesanciennes.com" + href

                out.append({
                    "id": _id(href),
                    "titre": texte[:90],
                    "description": texte,
                    "prix": _montant(texte, dernier=True),
                    "annee": _annee(texte),
                    "km": _km_texte(texte),
                    "lieu": "",
                    "pays": "France",
                    "url": href,
                    "image": img,
                    "source": "lesAnciennes",
                })
        except Exception as e:
            erreurs.append(str(e))
            print(f"  ! lesAnciennes : {e}")
        time.sleep(PAUSE)
    _verdict("lesAnciennes", out, erreurs, len(ANCIENNES_URLS))
    return out


# --------------------------------------------------------------------------
# 3. ParuVendu : beaucoup de particuliers en province, souvent sous-cote.
#    On passe par les pages SEO par marque : l'endpoint de recherche ignore le
#    filtre marque passe en parametre et renvoie des Peugeot.
#    /voiture-occasion/mini/ ne contient que des Mini BMW modernes ; ce sont
#    austin et rover qui portent les classiques.
# --------------------------------------------------------------------------


PARUVENDU_MARQUES = ["austin", "rover", "mini"]

# Carte ParuVendu : "<nb photos> <prix> € [a debattre] [Garantie N Mois]
#                    <titre> <Ville> (<CP>) Annee <aaaa> <km> km ..."
PV_BRUIT = re.compile(r"^\s*(?:à débattre|a débattre|south_east|Voiture|"
                      r"Garantie\s+\d+\s+Mois|Annonce à la une)\s*", re.I)
PV_VILLE = re.compile(r"([A-ZÀ-Þ][\wÀ-ÿ'’\-]*(?:[ \-][\wÀ-ÿ'’\-]+){0,3})\s*\((\d{5})\)")


def _carte_paruvendu(texte: str) -> tuple[str, str]:
    """Renvoie (titre, lieu) : le compteur de photos et le prix ouvrent la
    carte, il faut les retirer avant d'avoir quelque chose de lisible."""
    apres = texte.split("€", 1)[1] if "€" in texte else texte
    precedent = None
    while precedent != apres:
        precedent = apres
        apres = PV_BRUIT.sub("", apres)

    ville = PV_VILLE.search(apres)
    lieu = f"{ville.group(1)} ({ville.group(2)})" if ville else ""
    titre = apres[:ville.start()] if ville else re.split(r"\bAnn[eé]e\b", apres)[0]
    return _propre(titre) or _propre(texte), lieu


def paruvendu() -> list:
    out, erreurs = [], []
    for marque in PARUVENDU_MARQUES:
        u = f"https://www.paruvendu.fr/voiture-occasion/{marque}/"
        try:
            soup = BeautifulSoup(_get(u), "html.parser")
            for carte in soup.select(".blocAnnonce"):
                texte = _propre(carte.get_text(" ", strip=True))
                a = carte.find("a", href=True)
                if not a or "mini" not in texte.lower():
                    continue

                # "Année 2019" : les Mini BMW modernes sortent ici
                m = re.search(r"Ann[eé]e\s*(\d{4})", texte)
                annee = int(m.group(1)) if m else _annee(texte)
                if annee and annee > 2001:
                    continue

                href = a["href"]
                if href.startswith("/"):
                    href = "https://www.paruvendu.fr" + href

                titre, lieu = _carte_paruvendu(texte)
                out.append({
                    "id": _id(href),
                    "titre": titre[:110],
                    "description": texte,
                    "prix": _montant(texte),
                    "annee": annee,
                    "km": _km_texte(texte),
                    "lieu": lieu,
                    "pays": "France",
                    "url": href,
                    "image": "",
                    "source": "ParuVendu",
                })
        except Exception as e:
            erreurs.append(str(e))
            print(f"  ! ParuVendu {marque} : {e}")
        time.sleep(PAUSE)
    _verdict("ParuVendu", out, erreurs, len(PARUVENDU_MARQUES))
    return out

# --------------------------------------------------------------------------
# 4 et 5. eBay et Car & Classic : bloques par Akamai et Cloudflare.
#    Le code reste, desactive dans config.json, pour le jour ou on branchera
#    l'API Browse d'eBay. Tel quel, ces deux fonctions renvoient un 403.
# --------------------------------------------------------------------------


def ebay() -> list:
    base = "https://www.ebay.{}/sch/i.html?_nkw={}&_sop=10&_udhi=7000"
    cibles = [
        (base.format("fr", "austin+mini+ancienne"), "France"),
        (base.format("de", "austin+mini+oldtimer"), "Allemagne"),
    ]
    out = []
    for url, pays in cibles:
        try:
            soup = BeautifulSoup(_get(url), "html.parser")
            for li in soup.select("li.s-item, li[class*=s-card]"):
                titre = li.select_one(".s-item__title, [class*=title]")
                lien = li.find("a", href=True)
                prix_el = li.select_one(".s-item__price, [class*=price]")
                if not (titre and lien):
                    continue
                t = _propre(titre.get_text(" ", strip=True))
                if "mini" not in t.lower():
                    continue
                out.append({
                    "id": _id(lien["href"]), "titre": t, "description": t,
                    "prix": _prix(prix_el.get_text() if prix_el else 0),
                    "annee": _annee(t), "km": 0, "lieu": "", "pays": pays,
                    "url": lien["href"].split("?")[0], "image": "", "source": "eBay",
                })
            time.sleep(PAUSE)
        except Exception as e:
            print(f"  ! eBay {pays} : {e}")
    return out


def carandclassic() -> list:
    url = "https://www.carandclassic.com/search?q=mini&sort=newest"
    out = []
    try:
        soup = BeautifulSoup(_get(url), "html.parser")
        for a in soup.select("a[href*='/car/'], a[href*='/l/']"):
            txt = _propre(a.get_text(" ", strip=True))
            if not txt or "mini" not in txt.lower():
                continue
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.carandclassic.com" + href
            out.append({
                "id": _id(href), "titre": txt[:90], "description": txt,
                "prix": _montant(txt),
                "annee": _annee(txt), "km": 0, "lieu": "", "pays": "Royaume-Uni",
                "url": href, "image": "", "source": "Car & Classic",
            })
    except Exception as e:
        print(f"  ! Car & Classic : {e}")
    return out


TOUTES = {
    "leParking": leparking,
    "lesAnciennes": lesanciennes,
    "ParuVendu": paruvendu,
    "eBay": ebay,
    "Car & Classic": carandclassic,
}
