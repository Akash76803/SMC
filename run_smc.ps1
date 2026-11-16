# One-command local SMC trading-research terminal (read-only).
# No automatic trades, no option premium projections.
param(
    [ValidateSet("NIFTY","SENSEX")][string]$Symbol = "NIFTY",
    [switch]$Live,
    [int]$Port = 8765,
    [string]$Token = ""
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "Virtual environment missing. Run: py -3 -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -e '.[dev,angel]'"
    exit 1
}

$lower = $Symbol.ToLowerInvariant()
$raw = "data\${lower}_angel_historical_raw.csv"
$report = "results\v316_${lower}_report.json"
$brackets = "results\v316_${lower}_brackets.csv"
$ict = "results\v316_${lower}_ict.csv"
$liveFile = "results\live_${lower}.jsonl"
if (-not (Test-Path $raw)) {
    Write-Error "Historical CSV not found: $raw . Download verified index history first."
    exit 2
}

& $python -m smc.historical_replay_v314_cli --symbol $Symbol --input-csv $raw --out $report --candidates-csv $brackets --ict-csv $ict
if ($LASTEXITCODE -ne 0) {
    Write-Error "Historical replay failed; terminal not launched."
    exit $LASTEXITCODE
}

Write-Host "SMC research terminal: http://127.0.0.1:$Port"
Write-Host "Browser can open the address above. Press Ctrl+C to stop."
Write-Host "NO LIVE ORDERS | INDEX RESEARCH ONLY | NO VERIFIED OPTION PNL"

$argsList = @("-m","smc.app_terminal_v316","--symbol",$Symbol,
              "--csv",$raw,"--report",$report,"--live-jsonl",$liveFile,
              "--port",$Port)
if ($Live) {
    $argsList += "--start-live"
    if ($Token.Trim()) { $argsList += @("--token",$Token.Trim()) }
}

& $python @argsList
exit $LASTEXITCODE
