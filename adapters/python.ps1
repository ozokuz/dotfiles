function Find-EnvironmentPython {
    $candidates = @()
    if ($env:LOCALAPPDATA) {
        $candidates += Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -ExpandProperty FullName
    }
    $command = Get-Command python -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch 'WindowsApps[\\/]python') { $candidates += $command.Source }
    foreach ($candidate in $candidates) {
        & $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    return $null
}
