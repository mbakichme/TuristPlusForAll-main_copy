# ============================================================================
# TuristPlus — JEDNOKRATNI SETUP za Windows Server (PowerShell KAO ADMIN)
#
# Upotreba (PowerShell "Run as Administrator"):
#   powershell -ExecutionPolicy Bypass -File 00-setup.ps1
#   (opciono: -AppDir "D:\TuristPlus" -Port 8000)
#
# Idempotentna — može se pokrenuti više puta.
#
# Šta radi:
#   1) proverava git (instalira preko winget ako postoji, inače uputstvo)
#   2) instalira uv i bun (kopira u C:\Tools — stabilna putanja za servis)
#   3) klonira repo u C:\TuristPlus
#   4) uv sync (donosi Python 3.12 sam ako ga nema) + bun build → dist\
#   5) kreira .env.production (JWT generiše sam; NEON URL MORAŠ upisati ručno!)
#      i upisuje vrednosti u MACHINE environment (servis ih nasleđuje)
#   6) otvara port 8000 u firewall-u
#   7) WinSW Windows servis "TuristPlus" (uvicorn iz .venv, auto-restart, logovi)
#
# POSLE SETUP-A: upiši EXTERNAL_NEON_DATABASE_URL u .env.production pa
# ponovo pokreni ovu skriptu (upisaće env i startovati servis).
# ============================================================================
param(
    [string]$AppDir = "C:\TuristPlus",
    [string]$RepoUrl = "https://github.com/ignjatovicmilisav/TuristPlus.git",
    [string]$Port = "8000"
)
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ── mora Administrator ──────────────────────────────────────────────────────
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Pokreni PowerShell KAO ADMINISTRATOR."; exit 1
}

Write-Host "── [1/7] git ────────────────────────────────────────────────────────────"
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    try {
        winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + $env:Path
    } catch {
        Write-Host "winget nije dostupan. Instaliraj Git for Windows ručno:"
        Write-Host "  https://git-scm.com/download/win   (podrazumevane opcije su OK)"
        Write-Host "pa pokreni skriptu ponovo."; exit 1
    }
}

Write-Host "── [2/7] uv + bun (kopirani u C:\Tools za servis) ───────────────────────"
New-Item -ItemType Directory -Force -Path "C:\Tools\uv", "C:\Tools\bun" | Out-Null
if (-not (Test-Path "C:\Tools\uv\uv.exe")) {
    irm https://astral.sh/uv/install.ps1 | iex
    Copy-Item "$env:USERPROFILE\.local\bin\uv.exe" "C:\Tools\uv\uv.exe" -Force
}
if (-not (Test-Path "C:\Tools\bun\bun.exe")) {
    irm https://bun.sh/install.ps1 | iex
    Copy-Item "$env:USERPROFILE\.bun\bin\bun.exe" "C:\Tools\bun\bun.exe" -Force
}
$uv  = "C:\Tools\uv\uv.exe"
$bun = "C:\Tools\bun\bun.exe"

Write-Host "── [3/7] Repo: $AppDir ───────────────────────────────────────────────────"
if (-not (Test-Path "$AppDir\.git")) {
    git clone $RepoUrl $AppDir
}

Write-Host "── [4/7] Zavisnosti + build frontend-a ──────────────────────────────────"
Push-Location $AppDir
try {
    & $uv sync --frozen
    if ($LASTEXITCODE -ne 0) { throw "uv sync nije uspeo" }
    & $bun install --frozen-lockfile
    if ($LASTEXITCODE -ne 0) { throw "bun install nije uspeo" }
    & $bun run build
    if ($LASTEXITCODE -ne 0) { throw "bun run build nije uspeo" }
    if (-not (Test-Path "$AppDir\dist\index.html")) { throw "dist\index.html ne postoji — build nije uspeo" }
} finally { Pop-Location }

Write-Host "── [5/7] Secrets (.env.production + machine environment) ────────────────"
$envFile = Join-Path $AppDir ".env.production"
if (-not (Test-Path $envFile)) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $bytes = New-Object byte[] 32; $rng.GetBytes($bytes)
    $jwt = ([BitConverter]::ToString($bytes) -replace "-", "").ToLower()
    @"
# TuristPlus production secrets — NIKAD ne commit-ovati u git!
# OBAVEZNO upiši konekcioni string Neon baze (isti kao u Workshopu):
EXTERNAL_NEON_DATABASE_URL=
# Automatski generisan JWT ključ:
JWT_SECRET_KEY=$jwt
"@ | Set-Content -Path $envFile -Encoding UTF8
    icacls $envFile /inheritance:r /grant:r "BUILTIN\Administrators:F" "NT AUTHORITY\SYSTEM:F" | Out-Null
}
# parse KEY=VALUE → machine environment (servis (LocalSystem) ih nasleđuje)
$secrets = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { $secrets[$Matches[1]] = $Matches[2] }
}
foreach ($k in $secrets.Keys) {
    [Environment]::SetEnvironmentVariable($k, $secrets[$k], "Machine")
}
$dbUrl = $secrets["EXTERNAL_NEON_DATABASE_URL"]

Write-Host "── [6/7] Firewall port $Port ─────────────────────────────────────────────"
New-NetFirewallRule -DisplayName "TuristPlus $Port" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -ErrorAction SilentlyContinue | Out-Null

Write-Host "── [7/7] Windows servis (WinSW) ─────────────────────────────────────────"
# stari servis ukloni (idempotentno)
$existing = Get-Service -Name TuristPlus -ErrorAction SilentlyContinue
if ($existing) {
    Stop-Service TuristPlus -Force -ErrorAction SilentlyContinue
    & "$AppDir\turistplus-service.exe" uninstall | Out-Null
    Start-Sleep -Seconds 2
}
# WinSW v2.12.0 (zahteva .NET Framework 4.6.1+ — na serveru već postoji)
Invoke-WebRequest -Uri "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe" -OutFile "$AppDir\turistplus-service.exe"

$serviceXml = @"
<service>
  <id>TuristPlus</id>
  <name>TuristPlus Admin</name>
  <description>TuristPlus admin (FastAPI + static frontend), port $Port</description>
  <executable>$AppDir\.venv\Scripts\uvicorn.exe</executable>
  <arguments>app:asgi --host 127.0.0.1 --port $Port --workers 1 --proxy-headers --forwarded-allow-ips=127.0.0.1</arguments>
  <workingdirectory>$AppDir</workingdirectory>
  <log mode="roll-by-size">
    <logpath>$AppDir\logs</logpath>
    <logsize>10240</logsize>
    <keepfiles>8</keepfiles>
  </log>
  <onfailure action="restart" delay="5 sec"/>
</service>
"@
# službeni service account je LocalSystem — machine env je nasleđuje
$serviceXml | Set-Content "$AppDir\turistplus-service.xml" -Encoding UTF8

& "$AppDir\turistplus-service.exe" install
if ($dbUrl) {
    Start-Service TuristPlus
    Start-Sleep -Seconds 3
    Get-Service TuristPlus | Format-Table -AutoSize
    Write-Host ""
    Write-Host "GOTOVO. Aplikacija: http://$env:COMPUTERNAME`:$Port  (static + /api zajedno)"
    Write-Host "Logovi: $AppDir\logs  |  Test: http://127.0.0.1:$Port/api/mesto"
    Write-Host "HTTPS domen: vidi deploy\windows\Caddyfile.example"
} else {
    Write-Host ""
    Write-Host "=========================================================="
    Write-Host " STOP: upisi EXTERNAL_NEON_DATABASE_URL u:"
    Write-Host "   $envFile"
    Write-Host " pa ponovo pokreni ovu skriptu (startovaće servis)."
    Write-Host "=========================================================="
}
