# Authenticode-sign a built AvialView artifact.
#
# Release CI runs this only when the signing secrets exist, so an unsigned
# build stays possible for forks and for local work (BLUEPRINT.md Phase 5:
# "signing/notarization steps stubbed behind secrets-present conditionals").
#
#   pwsh packaging/windows/sign.ps1 -Path installer-output/AvialView-Setup.exe
#
# Environment:
#   WINDOWS_CERTIFICATE_PFX       base64 of a code-signing .pfx
#   WINDOWS_CERTIFICATE_PASSWORD  password for that .pfx
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Path,
    # RFC 3161 timestamping: without it every signature expires with the
    # certificate, and already-shipped installers start warning.
    [string]$TimestampUrl = 'http://timestamp.digicert.com'
)

$ErrorActionPreference = 'Stop'

foreach ($name in 'WINDOWS_CERTIFICATE_PFX', 'WINDOWS_CERTIFICATE_PASSWORD') {
    if (-not (Test-Path "env:$name") -or -not (Get-Item "env:$name").Value) {
        throw "sign.ps1: $name is not set; refusing to continue."
    }
}
if (-not (Test-Path $Path)) {
    throw "sign.ps1: nothing to sign at $Path"
}

$signtool = Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\bin' `
    -Filter 'signtool.exe' -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match 'x64' } |
    Sort-Object FullName -Descending |
    Select-Object -First 1
if ($null -eq $signtool) {
    throw 'sign.ps1: signtool.exe not found; the Windows SDK is required.'
}

$certificate = Join-Path $env:RUNNER_TEMP 'avialview-certificate.pfx'
try {
    [IO.File]::WriteAllBytes(
        $certificate,
        [Convert]::FromBase64String($env:WINDOWS_CERTIFICATE_PFX)
    )
    & $signtool.FullName sign `
        /f $certificate `
        /p $env:WINDOWS_CERTIFICATE_PASSWORD `
        /fd SHA256 /tr $TimestampUrl /td SHA256 `
        /d 'AvialView' `
        $Path
    if ($LASTEXITCODE -ne 0) { throw "sign.ps1: signtool failed ($LASTEXITCODE)" }

    & $signtool.FullName verify /pa /v $Path
    if ($LASTEXITCODE -ne 0) { throw "sign.ps1: signature verification failed" }
}
finally {
    # The certificate must not outlive the job that wrote it.
    Remove-Item $certificate -Force -ErrorAction SilentlyContinue
}
