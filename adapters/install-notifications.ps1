param(
    [Parameter(Mandatory)][string]$Repo,
    [Parameter(Mandatory)][string]$HostName,
    [Parameter(Mandatory)][string]$State
)
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/python.ps1"
$python = Find-EnvironmentPython
if (-not $python) { throw "Python 3.11+ is required." }
$arguments = '"' + "$Repo\env.py" + '" --host "' + $HostName + '" --state "' + $State + '" check --fetch --notify'
$action = New-ScheduledTaskAction -Execute $python -Argument $arguments
$logon = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$periodic = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$name = "Environment configuration - $HostName"
$existing = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Actions.Execute -ne $python -or $existing.Actions.Arguments -ne $arguments) {
        throw 'Existing notification task differs. Review and remove it explicitly before replacing.'
    }
} else {
    Register-ScheduledTask -TaskName $name -Action $action -Trigger @($logon, $periodic) -Principal $principal | Out-Null
}
