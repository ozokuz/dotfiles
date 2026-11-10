$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/adapters/python.ps1"
$python = Find-EnvironmentPython
if (-not $python) { throw 'Python 3.11+ is required. Run bootstrap.ps1 first.' }
& $python "$PSScriptRoot/env.py" @args
exit $LASTEXITCODE
