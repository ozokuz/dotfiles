param(
    [Parameter(Mandatory)][ValidateSet('get','set')][string]$Action,
    [Parameter(Mandatory)][string]$Path
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
if ($Action -eq 'set') {
    $clear = [Text.Encoding]::UTF8.GetBytes([Console]::In.ReadToEnd())
    try {
        $cipher = [Security.Cryptography.ProtectedData]::Protect($clear, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        [IO.File]::WriteAllBytes($Path, $cipher)
    } finally { [Array]::Clear($clear, 0, $clear.Length) }
} else {
    $clear = [Security.Cryptography.ProtectedData]::Unprotect([IO.File]::ReadAllBytes($Path), $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
    try { [Console]::Out.Write([Text.Encoding]::UTF8.GetString($clear)) }
    finally { [Array]::Clear($clear, 0, $clear.Length) }
}
