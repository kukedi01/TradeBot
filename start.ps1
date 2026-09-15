# Starts the backend and frontend as processes that survive this window
# closing, and does nothing if they are already up.
#
# Why this exists: over one 194-hour session the bot was down for 12.1 hours
# across 8 separate outages, the longest 7.7 hours. The cause was not a crash
# -- it was the servers being launched as children of a terminal that later
# went away, orphaning them. Every gap is a hole in the trading record and,
# now, in the order-flow dataset being collected.
#
# Usage: right-click -> "Run with PowerShell", or from a terminal:
#   powershell -ExecutionPolicy Bypass -File C:\Cripto\start.ps1
#
# Stop them again with: C:\Cripto\stop.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

function Test-PortListening([int]$Port) {
    $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

# Backend
if (Test-PortListening 8000) {
    Write-Host "Backend mar fut (8000-es port)." -ForegroundColor Yellow
} else {
    $python = Join-Path $root "backend\.venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        Write-Host "Nem talalom a venv-et: $python" -ForegroundColor Red
        Write-Host "Eloszor hozd letre: cd backend; python -m venv .venv; .venv\Scripts\python.exe -m pip install -r requirements.txt"
        exit 1
    }
    Start-Process -FilePath $python `
        -ArgumentList "-m", "uvicorn", "app.main:app", "--port", "8000", "--reload", "--reload-dir", "app" `
        -WorkingDirectory (Join-Path $root "backend") `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "backend.log") `
        -RedirectStandardError (Join-Path $logDir "backend.err.log")
    Write-Host "Backend elindult -> http://localhost:8000" -ForegroundColor Green
}

# Frontend
if (Test-PortListening 5173) {
    Write-Host "Frontend mar fut (5173-as port)." -ForegroundColor Yellow
} else {
    $env:Path += ";C:\Program Files\nodejs"
    Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run", "dev" `
        -WorkingDirectory (Join-Path $root "frontend") `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "frontend.log") `
        -RedirectStandardError (Join-Path $logDir "frontend.err.log")
    Write-Host "Frontend elindult -> http://localhost:5173" -ForegroundColor Green
}

Start-Sleep -Seconds 6
Write-Host ""
Write-Host ("Backend  8000: " + $(if (Test-PortListening 8000) { "fut" } else { "NEM fut -- nezd meg a logs\backend.err.log fajlt" }))
Write-Host ("Frontend 5173: " + $(if (Test-PortListening 5173) { "fut" } else { "NEM fut -- nezd meg a logs\frontend.err.log fajlt" }))
