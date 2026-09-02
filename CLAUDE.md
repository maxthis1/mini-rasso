# Mini Rasso — contexte projet

Fichier de contexte permanent. À lire au début de chaque session.

## Ce que c'est

Un radar d'annonces pour l'achat d'une Mini classique (Austin, Rover, Morris,
Innocenti, 1959–2000). Il surveille les sites marchands en France et chez les
voisins, note chaque annonce de 0 à 100, et envoie une notification push quand
une pépite apparaît.

On cherche soit une Mini qui roule bien avec quelques travaux, soit un projet
sain à moyen terme — jamais une épave, et surtout jamais de gros chantier de
tôlerie, la rouille étant le poste qui ruine ce type de projet. L'objectif
derrière l'achat est d'apprendre la mécanique en pratique, d'où ce curseur.

Le budget de recherche vit dans `config.json`, et le contexte personnel qui
l'explique dans `CONTEXTE-LOCAL.md`, **non suivi par git** : ce dépôt est public
parce que le site y lit ses données, et l'épargne de quelqu'un n'a rien à faire
sur une page indexée. Lis ce fichier au début de chaque session, il est à la
racine à côté de celui-ci.

Réalité du marché relevée en septembre 2026 : médiane des Austin Mini en France
à ~24 000 €, les moins chères qui roulent à 7 900–8 900 €. Au bas de la
fourchette on ne trouve que des chantiers. La piste réaliste au petit budget est
le **sud de l'Europe** (Espagne, Portugal, Italie), où l'absence de corrosion
compense un état mécanique moyen. Ce raisonnement est encodé dans le scoring :
les mots-clés géographiques du sud donnent un bonus, les signaux rouille un gros
malus.

La première collecte réelle a confirmé la thèse et corrigé les chiffres — voir
« Ce que le marché dit vraiment » plus bas.

## Stack et hébergement

Pas de framework, pas de build. HTML/CSS/JS vanilla + Python pour la collecte.

- **GitHub** : héberge le code et fait tourner le collecteur (Actions, cron 30 min).
  Le workflow réécrit `data/annonces.json` et le commit dans le dépôt.
- **Netlify** : sert le site, sur le dépôt qui hébergeait auparavant un site de sport.
  Ce site de sport doit être **archivé dans `_archive-sport/`, jamais supprimé**.
- **Le site lit les données sur `raw.githubusercontent.com`**, pas sur le fichier
  local. Raison : `netlify.toml` bloque les redéploiements quand seul `data/` change
  (sinon 1 440 déploiements/mois contre 300 minutes de quota gratuit). La constante
  `SOURCE` en haut du script de `index.html` porte cette URL.
- **Domaine** : minirasso.com, à brancher côté Netlify (pas de fichier CNAME).
- **Notifications** : ntfy.sh, topic secret passé par le secret GitHub `NTFY_TOPIC`.

## Arborescence

    index.html              le site entier (styles et script inline, volontairement)
    netlify.toml            publication + règle anti-redéploiement
    config.json             tous les réglages : budget, pays, mots-clés, seuils
    data/annonces.json      sortie du collecteur, réécrite à chaque passage
    collector/collect.py    orchestration, déduplication, détection des nouveautés, push
    collector/sources.py    un adaptateur par site, isolés les uns des autres
    collector/score.py      moteur de notation
    collector/fixture.json  jeu d'essai hors ligne
    .github/workflows/radar.yml

## Le scoring, en bref

`score.py` combine quatre choses, plafonnées à 100 :

1. **Écart à la cote (55 pts max)** — le prix demandé face à la cote de la classe
   d'état devinée dans le texte : `epave` 900 € · `projet` 2 600 € · `projet_sain`
   4 800 € · `bon_etat` 9 500 € · `tres_bon` 16 000 €.
2. **Mots-clés (+32 / −60)** — bonus sur les preuves (coque neuve, CT vierge,
   factures, moteur refait), malus sur rouille et épave. Les **négations sont
   gérées** : « aucune corrosion » et « traitement anticorrosion » ne pénalisent pas.
   C'est fragile, toute modification de `_mots()` doit être retestée sur la fixture.
3. **Budget (+15 / −10)** — bonus si payable comptant aujourd'hui.
4. **Coefficient pays** — pénalise distance et complexité d'import (UK à 0,6 :
   volant à droite et formalités post-Brexit).

Seuil de notification : 72, ou 55 si l'annonce est sous 2 500 €.

Avant le scoring, `exclure()` écarte les miniatures et lots de pièces, les prix
sous 200 €, ceux au-dessus du plafond, les pays absents de `config.json`, et
deux filtres qui visent la même chose — ne pas confondre la Mini classique avec
la MINI de BMW : la liste `exclusions.modeles_modernes` (R50, Countryman, JCW…)
et `recherche.annee_max` à **2000**, la Mini classique s'arrêtant en octobre
2000. Laisser 2001 faisait remonter des R50 à 650 € en tête de classement.
Une annonce sans millésime est écartée aussi : ce n'est pas vérifiable, et en
pratique c'est presque toujours une BMW récente.

Test de non-régression : `python collector/collect.py --fixture --dry-run`,
puis vérifier l'ordre attendu — 83 Mayfair · 76 Sprite espagnole · 53 Innocenti
· 22 automatique · 0 épave, les deux autres annonces d'essai étant exclues
(miniature 1/18, et une Cooper à 16 500 € au-dessus du plafond). Le jeu d'essai
ne lit ni n'écrit `data/annonces.json` : il affiche seulement son classement.

Pour inspecter la collecte réelle source par source :
`python collector/collect.py --dry-run --detail`, et
`--source leParking` pour n'en lancer qu'une, même désactivée.

## Sources

Toutes ont été validées sur données réelles le 2 septembre 2026. Règle absolue :
une source qui tombe ne casse jamais la collecte, elle est marquée en erreur et
affichée en pied de site.

**leParking** est le gros morceau : méta-moteur agrégeant ~960 sites (leboncoin,
La Centrale, AutoScout24, mobile.de, 2ememain, lesAnciennes), lu via les blocs
JSON-LD `schema.org/Vehicle`. Trois choses à savoir, chacune vérifiée :

- On n'interroge **qu'un seul domaine, `leparking.be`**. Tous les autres
  (`.fr`, `.es`, `.it`, `.pt`, `.de`, `.ch`, `theparking.eu`) répondent 403
  derrière un challenge JavaScript Cloudflare. Ce n'est pas un repli au rabais :
  le méta-moteur est le même et le `.be` renvoie les annonces de toute l'Europe.
  Le pays vient du bloc JSON-LD (`offers.availableAtOrFrom.address`), plus du
  domaine interrogé. Un pays absent de `config.json` est exclu — leParking
  remonte aussi des annonces américaines.
- Leur JSON-LD contient des **retours à la ligne bruts dans les valeurs** :
  `json.loads` échoue sans `strict=False`. C'est ce seul détail qui faisait
  renvoyer zéro annonce à la source la plus importante du radar.
- La **pagination est en JavaScript**, aucun paramètre d'URL ne la pilote. On
  compense avec `?tri=prix_croissant`, qui met le bas du marché en première
  page — exactement le segment recherché. On lit chaque slug deux fois, en tri
  prix et en tri date.

**lesAnciennes** fonctionne mais vend au prix marchand : sur 41 annonces, une
seule passe sous le plafond de 7 000 €. Sa valeur est de **calibrer la cote**,
pas de trouver une affaire. Piège de parsing : chaque annonce apparaît dans deux
balises `<a>`, dont un lien vendeur au texte inutile (« Nîmes 22 »). On regroupe
par URL et on garde le texte le plus long. Le prix **ferme** la carte, après une
description tronquée : c'est la dernière occurrence qu'il faut prendre.

Règle valable pour les trois sources qui parsent du HTML : **ne jamais lire un
nombre avec un motif large.** Les cartes collent bout à bout le compteur de
photos, le prix, la date de publication et le kilométrage. Un motif permissif
donnait 8 565 385 km à une Mini et 1 020 980 € à une autre. Les constantes
`MONTANT` et `KILOMETRAGE` de `sources.py` exigent un nombre bien formé, et le
kilométrage est plafonné à 500 000 km.

**ParuVendu** passe par les pages SEO par marque, `/voiture-occasion/austin/` et
`/rover/`. L'ancienne URL de recherche renvoie 404, et l'endpoint actuel ignore
le filtre de marque passé en paramètre — il répond des Peugeot. `/mini/` ne
contient que des MINI BMW modernes ; ce sont `austin` et `rover` qui portent les
classiques.

**eBay et Car & Classic sont désactivés** dans `config.json`. eBay répond 403
(Akamai Bot Manager), Car & Classic 403 (Cloudflare). On ne cherche pas à
contourner une protection anti-robot : eBay se rebranchera par son API Browse
officielle avec une clé développeur, Car & Classic reste hors radar. Le code des
deux adaptateurs est conservé, simplement pas appelé.

Hors radar volontairement : Facebook Marketplace et les groupes Facebook Mini,
où passent les meilleures affaires. Pas d'API, scraping contraire aux CGU.

### Le risque qui reste

Ces 403 dépendent de l'adresse IP d'où part la requête. `leparking.be` répond
depuis une connexion domestique ; rien ne garantit qu'il réponde depuis un
runner GitHub, dont les IP de datacentre sont exactement ce que Cloudflare
filtre. **À vérifier au premier passage réel du workflow.** Le collecteur est
protégé : si aucune source ne répond alors qu'on avait déjà des annonces, il
laisse `data/annonces.json` intact plutôt que de tout marquer comme disparu.
Si le blocage se confirme, la sortie est de faire tourner la collecte ailleurs
qu'en Actions (un petit VPS, ou une machine à la maison) et de ne garder GitHub
que pour l'hébergement.

## Design

Palette tirée des teintes d'usine Mini, pas générique : `--nuit #0C1A16`,
`--capot #132922`, `--acier #204237`, `--ivoire #EFE9DA` (Old English White),
`--almond #8FA07E` (Almond Green), `--tartan #C7263B` (Tartan Red),
`--ambre #D9A441`. Typo : Bebas Neue pour les chiffres et les prix, Archivo pour
le reste. L'élément fort et unique de la page est le cadran type Smiths en
en-tête, repris en miniature comme jauge de score sur chaque annonce. Tout le
reste est volontairement calme : filets d'un pixel, rayon de 2 px, aucune ombre,
aucune animation d'entrée. Ne pas ajouter de cartes arrondies ni de dégradés.

## Ce que le marché dit vraiment

Premier relevé sur données réelles, 2 septembre 2026 : 277 annonces brutes,
81 retenues sous le plafond de 7 000 €, prix médian 5 500 €. Répartition par
pays : **Italie 43, France 26**, Royaume-Uni 6, Allemagne 4.

C'est plus encourageant que l'estimation de départ. On trouve des Mini qui
roulent à **3 000–4 500 €**, surtout en Italie, là où le relevé initial situait
le premier prix raisonnable à 7 900–8 900 €. La thèse du sud de l'Europe se
confirme donc, mais c'est l'**Italie** qui porte le segment abordable, pas
l'Espagne ni le Portugal — le coefficient pays mérite d'être revu dans ce sens.

Deux limites à garder en tête en lisant les scores :

- Les descriptions leParking sont des fiches techniques (année, kilométrage,
  énergie, couleur), **sans texte libre sur l'état**. Le moteur de mots-clés
  est donc presque aveugle sur cette source : il ne reste que l'écart à la cote
  et le coefficient pays. Un score leParking veut dire « bon prix affiché »,
  pas « bonne voiture ».
- 16 annonces sur 81 n'affichent pas de prix, et repartent avec les 20 points
  forfaitaires de `score.py`. À surveiller si elles remontent trop haut.

## À faire

1. Pousser le projet à la racine du dépôt Netlify, après avoir déplacé le site
   de sport dans `_archive-sport/`.
2. Renseigner `SOURCE` dans `index.html` (pseudo GitHub + nom du dépôt).
   C'est le seul réglage qui manque encore pour que le site affiche des données.
3. Créer le secret GitHub `NTFY_TOPIC`, lancer le workflow une première fois,
   et **regarder les logs** : c'est là qu'on saura si Cloudflare bloque le
   runner (voir « Le risque qui reste »).
4. Brancher minirasso.com côté Netlify.
5. **Recalibrer les cotes** de `score.py` sur les prix observés. Le relevé
   ci-dessus suggère déjà que `projet_sain` à 4 800 € est trop haut pour
   l'Italie et à peu près juste pour la France : une cote par pays serait plus
   fidèle qu'une cote unique.
6. Aller chercher l'état réel des candidats. Pour les annonces qui passent un
   certain score, ouvrir la page de détail et scorer sur son texte plutôt que
   sur la fiche technique — c'est ce qui rendrait le moteur de mots-clés utile
   sur leParking.
7. Historiser les prix par annonce pour repérer les vendeurs qui baissent
   progressivement — ce sont les plus négociables. La détection de baisse
   existe déjà (`baisse_prix`), il manque l'historique.
8. Rebrancher eBay par l'API Browse officielle si le volume manque.

## Conventions

- Interface, commentaires et commits en français.
- Pas de dépendance nouvelle sans raison forte : `requests` et `beautifulsoup4`,
  c'est tout.
- `index.html` reste un fichier unique et autonome.
- Les réglages vont dans `config.json`, jamais en dur dans le code.
