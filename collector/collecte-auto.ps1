# Collecte Mini Rasso lancee depuis la connexion domestique.
#
# Raison d'etre : leParking passe derriere Cloudflare, qui filtre les plages
# d'IP de datacentre. Depuis un runner GitHub il repond 403 sur chaque requete,
# depuis une connexion residentielle il repond normalement. Comme leParking
# porte 84 % de la couverture du radar, la collecte doit partir d'ici.
#
# Ce script est appele par une tache planifiee Windows. Il ne fait rien
# d'autre que : collecter, commiter si les donnees ont bouge, pousser.
# Le site lit ensuite data/annonces.json directement sur GitHub.

$ErrorActionPreference = 'Stop'
$projet = Split-Path -Parent $PSScriptRoot
Set-Location $projet

# Sous le Planificateur, la console tombe sur la page de code Windows et le
# journal se remplit de "┬À" a la place des "·" du collecteur. On force l'UTF-8
# des deux cotes : celui que Python ecrit, celui que PowerShell lit.
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$journal = Join-Path $projet 'collector\dernier-passage.log'
function Note($texte) {
    $ligne = "{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $texte
    Write-Output $ligne
    Add-Content -Path $journal -Value $ligne -Encoding UTF8
}

try {
    # Le topic ntfy vit dans .env.local, non suivi par git : le depot est
    # public, et qui connait le topic peut envoyer des notifications.
    $fichierEnv = Join-Path $projet '.env.local'
    if (Test-Path $fichierEnv) {
        foreach ($ligne in Get-Content $fichierEnv) {
            if ($ligne -match '^\s*([A-Z_]+)\s*=\s*(.+?)\s*$') {
                [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
            }
        }
    }

    Note 'collecte en cours'
    $sortie = & py collector/collect.py 2>&1
    if ($LASTEXITCODE -ne 0) { throw "le collecteur a echoue : $sortie" }
    Note (($sortie | Select-String 'annonces retenues').ToString().Trim())

    # Rien de neuf ? on ne fabrique pas un commit vide.
    git diff --quiet -- data/annonces.json
    if ($LASTEXITCODE -eq 0) { Note 'donnees inchangees, rien a pousser'; exit 0 }

    git add data/annonces.json
    git commit -q -m ("annonces {0}" -f (Get-Date -Format 'dd/MM HH:mm'))

    # Le depot peut avoir bouge (workflow lance a la main, autre machine).
    # Sur data/annonces.json c'est notre collecte qui fait foi : elle voit
    # leParking, pas celle d'en face.
    git push -q origin main 2>$null
    if ($LASTEXITCODE -ne 0) {
        Note 'le depot avait avance, rebase en gardant la collecte locale'
        git -c core.editor=true pull --rebase -q origin main 2>$null
        if (Test-Path (Join-Path $projet '.git\REBASE_HEAD')) {
            git checkout --theirs data/annonces.json
            git add data/annonces.json
            git -c core.editor=true rebase --continue 2>$null
        }
        git push -q origin main
        if ($LASTEXITCODE -ne 0) { throw 'envoi impossible apres rebase' }
    }
    Note 'donnees publiees'
}
catch {
    Note "ECHEC : $_"
    exit 1
}
