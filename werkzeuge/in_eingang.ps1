<#
CWB - Code Workbench
Legt einen Auftrag in den Eingangsordner (core/eingangsordner.py, Vorhaben
"Bruecke" Stufe B1, siehe wissen/plan_bruecke.md). Gedacht fuer
Zeitschaltungen: der Windows-Taskplaner ruft dieses Skript zur gewuenschten
Zeit auf, CWB holt die Datei beim naechsten Blick (Dateisystem-Ereignis oder
spaetestens nach zwei Sekunden) - auch bei gesperrter Sitzung, weil keine
Zwischenablage beteiligt ist.

Aufruf:
    werkzeuge\in_eingang.ps1 -Datei C:\Pfad\zum\block.txt
    werkzeuge\in_eingang.ps1 -Datei C:\Pfad\zum\block.txt -Projekt CWB -Quelle zeitschaltung

Die Zieldatei wird zuerst unter einem Namen mit der Endung ".json.teil"
geschrieben und danach per Rename-Item umbenannt: auf demselben Laufwerk ist
das atomar, so bekommt der Waechter in core/eingangsordner.py nie eine halb
geschriebene Datei zu sehen.
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Datei,

    [string]$Projekt = "",

    [string]$Quelle = "zeitschaltung"
)

$ErrorActionPreference = "Stop"

try {
    if (-not (Test-Path -LiteralPath $Datei -PathType Leaf)) {
        throw "Datei nicht gefunden: $Datei"
    }
    $text = Get-Content -LiteralPath $Datei -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($text)) {
        throw "Datei ist leer: $Datei"
    }

    $eingangsordner = Join-Path $env:LOCALAPPDATA "CWB\eingang"
    New-Item -ItemType Directory -Force -Path $eingangsordner | Out-Null

    $auftrag = [ordered]@{
        quelle  = $Quelle
        projekt = $Projekt
        text    = $text
    }

    $name = "eingang_{0}_{1}" -f (Get-Date -Format "yyyyMMdd_HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $zielName = "$name.json"
    $teil = Join-Path $eingangsordner "$name.json.teil"
    $ziel = Join-Path $eingangsordner $zielName

    $auftrag | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $teil -Encoding UTF8
    Rename-Item -LiteralPath $teil -NewName $zielName

    Write-Output "Auftrag abgelegt: $ziel"
}
catch {
    Write-Error "in_eingang.ps1 fehlgeschlagen: $_"
    exit 1
}
