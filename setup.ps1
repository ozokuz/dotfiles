# Standalone bootstrap: usable from a checkout or through irm | iex.
param(
    [string]$HostName = [Environment]::MachineName.ToLowerInvariant(),
    [switch]$AllowSystem,
    [switch]$Yes,
    [string]$ExpectedUserSid
)

function Invoke-EnvironmentBootstrap {
    param($HostName, [switch]$AllowSystem, [switch]$Yes, $ExpectedUserSid, $SourcePath)
    $ErrorActionPreference = 'Stop'
    if ($ExpectedUserSid -and [Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ne $ExpectedUserSid) {
        throw 'Elevation changed the user identity. Run setup under the intended account instead.'
    }
    $repository = if ($env:DOTFILES_REPOSITORY) { $env:DOTFILES_REPOSITORY } else { 'https://github.com/ozokuz/dotfiles.git' }
    $ref = if ($env:DOTFILES_REF) { $env:DOTFILES_REF } else { 'main' }
    $destination = if ($env:DOTFILES_DIRECTORY) { $env:DOTFILES_DIRECTORY } else { Join-Path $env:LOCALAPPDATA 'envstore/repository' }

    # Kept inline so no local files or preinstalled Python are required by iex.
    function Find-BootstrapPython {
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
    $python = Find-BootstrapPython
    if (-not $python -or -not (Get-Command git -ErrorAction SilentlyContinue) -or -not (Get-Command winget -ErrorAction SilentlyContinue)) {
        if (-not $Yes) {
            $answer = Read-Host 'Install missing setup prerequisites (WinGet, Python 3.11+, Git)? [y/N]'
            if ($answer -notin @('y', 'yes')) { throw 'Prerequisites not authorized.' }
        }
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            # Microsoft's documented user-scoped bootstrap also covers fresh
            # sessions where App Installer has not registered WinGet yet.
            if (Get-Command Add-AppxPackage -ErrorAction SilentlyContinue) {
                try { Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe } catch { }
            }
            if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
                [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
                Install-PackageProvider -Name NuGet -Force -Scope CurrentUser | Out-Null
                Install-Module -Name Microsoft.WinGet.Client -Force -Repository PSGallery -Scope CurrentUser | Out-Null
                Import-Module Microsoft.WinGet.Client
                Repair-WinGetPackageManager -Latest -Force
                $env:Path += ';' + (Join-Path $env:LOCALAPPDATA 'Microsoft/WindowsApps')
            }
            if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'WinGet registration failed.' }
        }
        if (-not $python) {
            & winget install --id Python.Python.3.13 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
        }
        if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
            & winget install --id Git.Git --exact --scope user --silent --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { throw 'Git installation failed.' }
        }
        $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
        $python = Find-BootstrapPython
        if (-not $python) { throw 'Python 3.11+ installation was not found.' }
    }

    $repo = $null
    if ($SourcePath -and (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        $parent = Split-Path -Parent $SourcePath
        if (Test-Path -LiteralPath (Join-Path $parent 'env.py')) { $repo = $parent }
    }
    if (-not $repo) {
        $repo = $destination
        if (Test-Path -LiteralPath $repo) {
            if (-not (Test-Path -LiteralPath (Join-Path $repo '.git')) -or -not (Test-Path -LiteralPath (Join-Path $repo 'env.py'))) {
                throw "Refusing to overwrite existing path: $repo"
            }
            $origin = & git -C $repo config --get remote.origin.url
            if ($LASTEXITCODE) { throw 'Cannot read checkout origin.' }
            $current = & git -C $repo symbolic-ref --quiet --short HEAD
            if ($LASTEXITCODE) { $current = & git -C $repo rev-parse HEAD }
            if ($LASTEXITCODE -or $origin -ne $repository -or $current -ne $ref) {
                throw 'Existing checkout has a different origin or ref; review it before rerunning bootstrap.'
            }
            Write-Host "Using existing checkout without changing it: $repo"
        } else {
            $null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $repo)
            & git clone --branch $ref --single-branch -- $repository $repo
            if ($LASTEXITCODE) { throw 'Configuration repository clone failed.' }
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $repo 'env.py'))) {
        throw 'The selected repository ref does not contain the environment store.'
    }

    $identity = $null
    if ($ExpectedUserSid -or $AllowSystem) {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        if ($ExpectedUserSid -and $identity.User.Value -ne $ExpectedUserSid) {
            throw 'Elevation changed the user identity. Run setup under the intended account instead.'
        }
    }
    $administrator = $identity -and ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $arguments = @('--host', $HostName, 'setup')
    if ($AllowSystem) { $arguments += '--allow-system' }
    if ($Yes) { $arguments += '--yes' }
    $code = 77
    if (-not $AllowSystem -or $administrator) {
        & $python (Join-Path $repo 'env.py') @arguments
        $code = $LASTEXITCODE
    }
    if ($code -eq 77) {
        # The checkout now exists even when the original invocation used iex.
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        if ($HostName -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_-]*$') { throw 'Invalid host name.' }
        $entry = Join-Path $repo 'setup.ps1'
        $elevated = '-NoProfile -ExecutionPolicy Bypass -File "' + $entry + '" -HostName "' + $HostName + '" -AllowSystem -ExpectedUserSid "' + $identity.User.Value + '"'
        if ($Yes) { $elevated += ' -Yes' }
        $child = Start-Process powershell.exe -Verb RunAs -ArgumentList $elevated -Wait -PassThru
        $code = $child.ExitCode
    }
    if ($code) { throw "Environment setup failed with exit code $code." }
}

# A script file and Invoke-Expression both return to their caller. Never exit the
# interactive PowerShell session that downloaded the bootstrap.
Invoke-EnvironmentBootstrap -HostName $HostName -AllowSystem:$AllowSystem -Yes:$Yes -ExpectedUserSid $ExpectedUserSid -SourcePath $PSCommandPath
