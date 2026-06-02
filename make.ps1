<#
.SYNOPSIS
  Equivalente del Makefile para Windows (PowerShell). El Makefile usa shell POSIX
  (`command -v`, `[ -z ]`, `cp`, `mkdir -p`, `grep`/`awk`) que no corre en cmd.exe /
  PowerShell, así que este script replica los mismos targets.

.DESCRIPTION
  Targets: help, install, install-analyzer, analyzer, transcribe, diarize, download, env.

.EXAMPLE
  .\make.ps1 install
  .\make.ps1 transcribe -Audio outputs\videos\pleno.mp4 --diarize --speakers 3
  .\make.ps1 diarize    -Audio outputs\videos\pleno.mp4 --speakers 3
  .\make.ps1 analyzer   -Transcript outputs\videos\otro.txt --debug
  .\make.ps1 download   -Url "https://...m3u8" -Output outputs\videos\pleno.mp4
  .\make.ps1 env

.NOTES
  Si PowerShell bloquea la ejecución de scripts, invócalo así (sin cambiar la política global):
    powershell -ExecutionPolicy Bypass -File .\make.ps1 transcribe -Audio ...
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet('help', 'install', 'install-analyzer', 'analyzer',
                 'transcribe', 'diarize', 'download', 'env')]
    [string]$Target = 'help',

    [string]$Audio,
    [string]$Url,
    [string]$Output = 'outputs\videos\descarga.mp4',
    [string]$Transcript,

    # Flags extra que se reenvían tal cual al comando (p. ej. --speakers 3 --model small).
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'
# Trabajamos desde la raíz del repo (donde vive este script) para que las rutas
# relativas (transcriber\, analyzer, .env_template) resuelvan igual que con make.
Set-Location -LiteralPath $PSScriptRoot

# Intérprete de Python: preferimos 'python'; si no, el lanzador 'py' de Windows.
function Get-Python {
    foreach ($candidate in 'python', 'py') {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) { return $candidate }
    }
    Write-Error "No se encontró Python en el PATH. Instálalo desde https://www.python.org/ y reabre la terminal."
}

function Invoke-Help {
    Write-Host "Targets disponibles (uso: .\make.ps1 <target> [opciones]):`n"
    $rows = @(
        @('install',          'Instala las dependencias del transcriptor'),
        @('install-analyzer', 'Instala las dependencias del chatbot (analyzer)'),
        @('analyzer',         'Arranca el chatbot de análisis (-Transcript, flags extra)'),
        @('transcribe',       'Transcribe un audio (-Audio, flags extra; --diarize para hablantes)'),
        @('diarize',          'Solo diarización, sin Whisper (-Audio, flags extra)'),
        @('download',         'Descarga/remux de un stream con ffmpeg (-Url, -Output)'),
        @('env',              'Crea el .env desde .env_template (no sobrescribe)')
    )
    foreach ($r in $rows) {
        Write-Host ("  {0,-18}" -f $r[0]) -ForegroundColor Cyan -NoNewline
        Write-Host (" {0}" -f $r[1])
    }
}

switch ($Target) {
    'help' { Invoke-Help }

    'install' {
        & (Get-Python) -m pip install -r transcriber\requirements.txt
    }

    'install-analyzer' {
        & (Get-Python) -m pip install -r analyzer\requirements.txt
    }

    'analyzer' {
        $cmd = @('-m', 'analyzer')
        if ($Transcript) { $cmd += $Transcript }
        if ($Rest)       { $cmd += $Rest }
        & (Get-Python) @cmd
    }

    'transcribe' {
        if (-not $Audio) {
            Write-Error 'Falta -Audio. Uso: .\make.ps1 transcribe -Audio outputs\videos\pleno.mp4 --speakers 3'
        }
        $cmd = @('transcriber\transcribe_diarize.py', $Audio)
        if ($Rest) { $cmd += $Rest }
        & (Get-Python) @cmd
    }

    'diarize' {
        if (-not $Audio) {
            Write-Error 'Falta -Audio. Uso: .\make.ps1 diarize -Audio outputs\videos\pleno.mp4 --speakers 3'
        }
        $cmd = @('transcriber\transcribe_diarize.py', $Audio, '--diarize-only')
        if ($Rest) { $cmd += $Rest }
        & (Get-Python) @cmd
    }

    'download' {
        if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
            Write-Error "ffmpeg no está instalado. Instálalo con: winget install Gyan.FFmpeg (o choco install ffmpeg) y reabre la terminal."
        }
        if (-not $Url) {
            Write-Error 'Falta -Url. Uso: .\make.ps1 download -Url "https://..." -Output outputs\videos\pleno.mp4'
        }
        $dir = Split-Path -Parent $Output
        if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        & ffmpeg -i $Url -c copy $Output
    }

    'env' {
        if (Test-Path -LiteralPath '.env') {
            Write-Host '.env ya existe, no se sobrescribe'
        }
        else {
            Copy-Item -LiteralPath '.env_template' -Destination '.env'
            Write-Host '.env creado desde .env_template — rellena HF_TOKEN y ANTHROPIC_API_KEY'
        }
    }
}
