$ErrorActionPreference='Stop'
$statePath=Join-Path $PSScriptRoot 'runtime\public\hosting.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'Public service is not running.'; exit 0 }
$state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
# Validate every process before stopping any; never touch the port 8502 workspace.
$targets=@()
foreach ($kind in @('supervisor','web','worker','tunnel')) {
    $serviceId=$state.($kind+'_pid')
    if (-not $serviceId) { continue }
    $service=Get-CimInstance Win32_Process -Filter "ProcessId = $serviceId" -ErrorAction SilentlyContinue
    if (-not $service) { continue }
    $matches=switch ($kind) {
        'supervisor' { $service.CommandLine -like ('*'+(Join-Path $PSScriptRoot 'public_host.py')+'*') }
        'web' { $service.CommandLine -like ('*'+(Join-Path $PSScriptRoot 'app.py')+'*') -and $service.CommandLine -like '*8503*' }
        'worker' { $service.CommandLine -like ('*'+(Join-Path $PSScriptRoot 'reminder_worker.py')+'*') -and $service.CommandLine -like '*--runtime-profile public*' }
        'tunnel' { $service.Name -eq 'cloudflared.exe' -and $service.CommandLine -like '*--url http://127.0.0.1:8503*' }
    }
    if (-not $matches) { throw "Process $serviceId does not match this public deployment. Nothing stopped." }
    $targets+=$serviceId
}
foreach ($serviceId in $targets) { Stop-Process -Id $serviceId -ErrorAction SilentlyContinue }
$state.phase='stopped'
$state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
Write-Host 'Public access stopped. Public records are retained; local port 8502 was not stopped.'
