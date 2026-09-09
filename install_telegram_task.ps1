$ErrorActionPreference = 'Stop'
$taskName = 'Sharpie Telegram Worker'
$workerPath = Join-Path $PSScriptRoot 'telegram_worker.ps1'
if (-not (Test-Path -LiteralPath $workerPath)) { throw 'No se encontro telegram_worker.ps1' }
$userId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType S4U -RunLevel Highest
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $workerPath) -WorkingDirectory $PSScriptRoot
$startup = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $startup -Settings $settings -Principal $principal -Description 'Suscripciones Telegram y avisos de picks; independiente del scraper.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State
