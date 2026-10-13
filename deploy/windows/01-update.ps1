# ============================================================================
# TuristPlus — AŽURIRANJE produkcije na noviju verziju (Windows, KAO ADMIN)
#
# Upotreba:
#   powershell -ExecutionPolicy Bypass -File 01-update.ps1
#   (opciono: -AppDir "D:\TuristPlus")
#
# Radi: git pull → zavisnosti → build frontend-a → restart servisa.
# Pretpostavlja da je 00-setup.ps1 već pokrenut jednom.
# ============================================================================
param(
    [string]$AppDir = "C:\TuristPlus"
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

if (-not (Test-Path "$AppDir\.git")) {
    Write-Host "GRESKA: $AppDir nije repo — prvo pokreni 00-setup.ps1"; exit 1
}

Write-Host "── [1/4] git pull ───────────────────────────────────────────────────────"
Push-Location $AppDir
try {
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw "git pull nije uspeo" }
} finally { Pop-Location }

Write-Host "── [2/4] Zavisnosti ─────────────────────────────────────────────────────"
Push-Location $AppDir
try {
    & "C:\Tools\uv\uv.exe" sync --frozen
    if ($LASTEXITCODE -ne 0) { throw "uv sync nije uspeo" }
    & "C:\Tools\bun\bun.exe" install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "bun install nije uspeo" }
} finally { Pop-Location }

Write-Host "── [3/4] Build frontend-a (tsc -b && vite build) ────────────────────────"
Push-Location $AppDir
try {
    & "C:\Tools\bun\bun.exe" run build
    if ($LASTEXITCODE -ne 0) { throw "build nije uspeo" }
    if (-not (Test-Path "$AppDir\dist\index.html")) { throw "dist\index.html ne postoji" }
} finally { Pop-Location }

Write-Host "── [4/4] Restart servisa ────────────────────────────────────────────────"
Restart-Service TuristPlus
Start-Sleep -Seconds 3
Get-Service TuristPlus | Format-Table -AutoSize
Write-Host ""
Write-Host "NOVA VERZIJA JE LIVE."
