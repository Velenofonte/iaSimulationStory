# Launch backend + frontend on 0.0.0.0 (LAN / cellulare).
# Usage (from repo root):
#   .\start.ps1
# Stop with Ctrl+C (stops both).

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"

$Python = $null
$VenvPython = Join-Path $BackendDir ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $Python = $VenvPython
} else {
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCmd) {
        $Python = $pyCmd.Source
    } else {
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCmd) { $Python = $pythonCmd.Source }
    }
}
if (-not $Python) {
    Write-Error "Python non trovato. Crea il venv in backend\.venv o installa Python."
}

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Host "node_modules assente: eseguo npm install..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    npm install
    Pop-Location
}

# Dev: API via proxy Vite (/api) — non forzare 127.0.0.1
Remove-Item Env:VITE_API_BASE -ErrorAction SilentlyContinue

Write-Host "Backend  http://0.0.0.0:8001  (LAN: http://<IP-PC>:8001)" -ForegroundColor Cyan
Write-Host "Frontend http://localhost:5173  (telefono: http://<IP-PC>:5173)" -ForegroundColor Cyan
Write-Host "PWA sul telefono: in Chrome abilita unsafely-treat-insecure-origin-as-secure per quell'URL." -ForegroundColor DarkGray
Write-Host "Ctrl+C per fermare entrambi.`n" -ForegroundColor DarkGray

$backend = Start-Process -FilePath $Python -ArgumentList @(
    "-m", "uvicorn", "app.main:app",
    "--reload", "--app-dir", ".",
    "--host", "0.0.0.0", "--port", "8001"
) -WorkingDirectory $BackendDir -PassThru -NoNewWindow

$frontend = Start-Process -FilePath "npm.cmd" -ArgumentList @(
    "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"
) -WorkingDirectory $FrontendDir -PassThru -NoNewWindow

try {
    Wait-Process -Id $backend.Id, $frontend.Id
} finally {
    foreach ($p in @($backend, $frontend)) {
        if ($p -and -not $p.HasExited) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            Get-CimInstance Win32_Process -Filter "ParentProcessId=$($p.Id)" -ErrorAction SilentlyContinue |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        }
    }
}
