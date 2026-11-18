@echo off
title SMC Terminal 9AM Auto-Launcher
cd /d "E:\Project\SMC"
echo [SMC] Starting SMC Terminal at 09:00 AM...
echo [SMC] Connecting to Angel One Dual Stream (NIFTY + SENSEX)...
powershell.exe -ExecutionPolicy Bypass -NoProfile -File "E:\Project\SMC\run_smc.ps1" -Live
pause

