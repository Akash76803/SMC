# Automated SMC Storage Retention & Cleanup Utility
param(
    [int]$RetentionDays = 7,
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python.exe"
}

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host " SMC STORAGE CLEANUP & HOUSEKEEPING " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

$argsList = @("-m", "smc.data_cleanup_manager", "--root", $root, "--retention-days", $RetentionDays)
if ($DryRun) {
    $argsList += "--dry-run"
}

& $python @argsList
Write-Host "`nCleanup check finished." -ForegroundColor Green

