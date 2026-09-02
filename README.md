# Mini Rasso

Surveille en continu les annonces de Mini classique (Austin, Rover, Morris, Innocenti)
en France et chez les voisins, les note de 0 a 100, et envoie une notification sur ton
telephone des qu'une pepite passe.

## Mise en ligne (10 minutes)

1. Pousse ce dossier a la racine du depot GitHub relie a Netlify. Netlify sert
   le site, GitHub Actions fait tourner le collecteur.
2. Dans `index.html`, renseigne la constante `SOURCE` avec ton pseudo GitHub et
   le nom du depot. Le site lit ses donnees sur `raw.githubusercontent.com` et
   non sur le fichier local, pour ne pas declencher un deploiement Netlify a
   chaque passage du collecteur (voir `netlify.toml`).
3. **Notifications** : installe l'app *ntfy* (iOS / Android, gratuite, sans compte),
   abonne-toi a un topic secret, par exemple `mini-radar-7f3k9x`.
   Puis **Settings → Secrets and variables → Actions → New repository secret** :
   nom `NTFY_TOPIC`, valeur `mini-radar-7f3k9x`.
4. **Actions** → autorise les workflows → `Mini Rasso` → *Run workflow* pour le
   premier passage, et regarde les logs : c'est la qu'on verra si les sites
   interroges acceptent les requetes venant d'un runner GitHub.

Ensuite ca tourne tout seul toutes les 30 minutes.

## Reglages

Tout se passe dans `config.json`, sans toucher au code :

| Cle | Effet |
|---|---|
| `budget.achat_immediat` | le seuil "je peux payer comptant tout de suite" |
| `budget.budget_cible` | ce que tu vises dans quelques mois |
| `budget.plafond_absolu` | au-dela, l'annonce n'est meme pas affichee |
| `notifications.score_minimum` | severite des push. 72 = quelques-uns par semaine. Monte a 80 si trop de bruit |
| `mots_cles.*` | les poids du scoring. Ajoute tes propres mots au fil des annonces vues |
| `pays` | coefficient par pays : baisse-le pour eloigner un pays, monte-le pour le favoriser. Un pays absent de la liste est exclu |
| `sources.*` | active ou coupe une source sans toucher au code |
| `exclusions.modeles_modernes` | ce qui distingue la Mini classique de la MINI de BMW |
| `recherche.annee_max` | 2000 : la Mini classique s'arrete en octobre 2000 |
| `retention.jours_apres_disparition` | combien de jours une annonce disparue reste affichee |

## Comment le score est calcule

- **Ecart a la cote (55 pts max)** — le prix demande face a la cote de marche de la
  classe d'etat devinee dans l'annonce (epave / projet / projet sain / bon etat / tres bon).
- **Mots-cles (+32 / −60)** — bonus sur les preuves (coque neuve, CT vierge, factures,
  moteur refait), malus sur les signaux rouille et epave. Les negations sont gerees :
  "aucune corrosion" et "traitement anticorrosion" ne penalisent pas.
- **Budget (+15 / −10)** — bonus si c'est payable comptant aujourd'hui.
- **Pays (coefficient)** — penalise la distance et la complexite d'import.

Un score de 80+ merite un appel le soir meme. En dessous de 45, c'est un chantier
ou un vendeur trop gourmand.

## Sources

`leParking` est le gros morceau : un meta-moteur qui aspire ~960 sites, dont
leboncoin, La Centrale, AutoScout24, mobile.de, 2ememain, lesAnciennes. Une
seule interrogation couvre toute l'Europe. S'y ajoutent `lesAnciennes` (prix
marchands, utile surtout pour calibrer la cote) et `ParuVendu`.

`eBay` et `Car & Classic` sont **desactives** dans `config.json` : ils repondent
403 a toute requete automatisee. Contourner une protection anti-robot n'est pas
une option ; eBay se rebranchera par son API officielle.

Restent hors radar, a surveiller a la main : **Facebook Marketplace** et les
**groupes Facebook Mini** (Mini Classic France, Mini Passion), ou passent les
meilleures affaires entre passionnes, et les **bourses d'echange**.

Une source qui tombe ne casse jamais la collecte : son etat s'affiche en bas du
site. Et si elles tombent toutes d'un coup, le collecteur laisse les donnees
existantes en place au lieu de les ecraser.

## Structure

    index.html            le site (autonome, aucun build)
    netlify.toml          config Netlify : publication et regle anti-redeploiement
    config.json           tous les reglages
    data/annonces.json    les donnees, reecrites a chaque passage
    collector/collect.py  orchestration, deduplication, notifications
    collector/sources.py  un adaptateur par site
    collector/score.py    le moteur de notation
    collector/fixture.json  jeu d'essai hors ligne

## En local

    pip install -r collector/requirements.txt
    python collector/collect.py --dry-run              # collecte sans notifier
    python collector/collect.py --dry-run --detail     # + un echantillon par source
    python collector/collect.py --source ParuVendu     # une seule source
    python collector/collect.py --fixture --dry-run    # test du scoring, sans reseau
    python -m http.server 8000                         # puis http://localhost:8000

Sous Windows, si `python` ouvre le Microsoft Store, utilise `py` a la place.
