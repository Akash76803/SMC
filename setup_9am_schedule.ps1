# Setup 09:00 AM IST Auto-Start for SMC Terminal
$TaskName = "SMCTerminal_9AM_AutoConnect"
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument '/c "E:\Project\SMC\run_smc_live_auto.bat"'
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At 9:00AM
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Auto-starts SMC Research Terminal with Angel One Live Stream at 9:00 AM every trading day."
    Write-Host "SUCCESS: Windows Scheduled Task '$TaskName' registered for 09:00 AM (Mon-Fri)." -ForegroundColor Green
} catch {
    Write-Warning "Could not register Task Scheduler directly: $_"
    Write-Host "Alternative schtasks command:" -ForegroundColor Yellow
    Write-Host 'schtasks /Create /SC WEEKLY /D MON,TUE,WED,THU,FRI /TN "SMCTerminal_9AM" /TR "E:\Project\SMC\run_smc_live_auto.bat" /ST 09:00 /F'
}

