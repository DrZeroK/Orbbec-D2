# Temporary CurrentUser/Session discovery only; cleanup restores the prior registry state.
param([switch]$Machine)
$ErrorActionPreference = 'Stop'
$d2RegistryRoot = if ($Machine) { [Microsoft.Win32.Registry]::LocalMachine } else { [Microsoft.Win32.Registry]::CurrentUser }
$d2SourceClsid = 'Software\Classes\CLSID\{265E13EF-0B32-4E1D-8A91-CFD17143D89C}'
$d2PriorRegistration = $d2RegistryRoot.OpenSubKey($d2SourceClsid)
if ($null -ne $d2PriorRegistration) { $d2PriorRegistration.Dispose(); throw 'D2 CLSID already exists; no registry values changed' }
$d2SourceDll = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'build\D2MediaSource.dll')).Path
$d2SourceExecutable = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'build\virtual_camera_probe.exe')).Path
$d2ProbeLog = Join-Path $PSScriptRoot $(if ($Machine) { 'build\system_source_machine_probe.log' } else { 'build\system_source_probe.log' })
try {
    $d2Registration = $d2RegistryRoot.CreateSubKey($d2SourceClsid)
    try {
        $d2Registration.SetValue('', 'D2 Infrared Research Source')
        $d2ServerRegistration = $d2Registration.CreateSubKey('InprocServer32')
        try {
            $d2ServerRegistration.SetValue('', $d2SourceDll)
            $d2ServerRegistration.SetValue('ThreadingModel', 'Both')
        } finally { $d2ServerRegistration.Dispose() }
    } finally { $d2Registration.Dispose() }
    & $d2SourceExecutable '{265E13EF-0B32-4E1D-8A91-CFD17143D89C}' 5 2>&1 | Set-Content -LiteralPath $d2ProbeLog -Encoding UTF8
    $d2SourceResult = $LASTEXITCODE
} finally {
    $d2RegistryRoot.DeleteSubKeyTree($d2SourceClsid, $false)
}
Get-Content -LiteralPath $d2ProbeLog
Write-Output "Registry cleanup complete; probe exit=$d2SourceResult"
exit $d2SourceResult
