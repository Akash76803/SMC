# Single local NIFTY/SENSEX SMC research terminal; optional read-only dual feed.
param(
    [switch]$Live,
    [int]$Port = 8765,
    [string]$NiftyToken = "",
    [string]$SensexToken = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Missing .venv. Run py -3 -m venv .venv and pip install -e '.[dev,angel]'"
    exit 1
}

# Fail before replay/login if an older terminal is still listening.
$active = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($active.Count -gt 0) {
    $owners = ($active | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    Write-Host "OLD_SERVER_DETECTED: Port $Port is already in use. PID: $owners" -ForegroundColor Yellow
    Write-Host "In a separate PowerShell, inspect: Get-CimInstance Win32_Process -Filter 'ProcessId=$($active[0].OwningProcess)' | Select ProcessId,CommandLine"
    Write-Host "Stop the OLD SMC PowerShell with Ctrl+C first; then launch this script again."
    exit 3
}
Write-Host "Launching updated SMC Dual Market dashboard (build SMC-DUAL-MARKET-2026-11-16-R2)" -ForegroundColor Cyan

# Recompute each index independently. Unavailable history stays UNAVAILABLE.
foreach ($symbol in @("NIFTY", "SENSEX")) {
    $lower = $symbol.ToLowerInvariant()
    $raw = "data\${lower}_angel_historical_raw.csv"
    $report = "results\v316_${lower}_report.json"
    $brackets = "results\v316_${lower}_brackets.csv"
    $ict = "results\v316_${lower}_ict.csv"
    if (Test-Path $raw) {
        & $python -m smc.historical_replay_v314_cli --symbol $symbol `
           --input-csv $raw --out $report --candidates-csv $brackets --ict-csv $ict
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "$symbol replay quality gate failed. No historical series will be invented."
            if (Test-Path $report) { Remove-Item $report -Force }
        }
    }
    else {
        Write-Host "$symbol historical CSV missing: $raw. Screen will display UNAVAILABLE."
        if (Test-Path $report) { Remove-Item $report -Force }
    }
}

Write-Host "SMC dual-market terminal: http://127.0.0.1:$Port"
Write-Host "Verify build: http://127.0.0.1:$Port/api/version"
Write-Host "Select NIFTY or SENSEX on screen. Ctrl+C to stop."
Write-Host "NO BROKER ORDERS | RESEARCH AND SIGNAL AUDIT ONLY"

$argsList = @("-m","smc.app_terminal_v316","--multi","--root",$PSScriptRoot,
              "--port",$Port,"--open-browser")
if ($Live) {
    $argsList += "--start-live"
    if ($NiftyToken.Trim()) { $argsList += @("--nifty-token",$NiftyToken.Trim()) }
    if ($SensexToken.Trim()) { $argsList += @("--sensex-token",$SensexToken.Trim()) }
}
& $python @argsList
exit $LASTEXITCODE
