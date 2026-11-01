$ErrorActionPreference='Stop'
$statePath=Join-Path $PSScriptRoot 'runtime\public\hosting.json'
$state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$targets=@()
foreach ($kind in @('supervisor','web')) {
    $serviceId=$state.($kind+'_pid')
    $service=Get-CimInstance Win32_Process -Filter "ProcessId = $serviceId"
    $expected=if ($kind -eq 'supervisor') { Join-Path $PSScriptRoot 'public_host.py' } else { Join-Path $PSScriptRoot 'app.py' }
    if (-not $service -or $service.CommandLine -notlike ('*'+$expected+'*')) { throw 'Existing public process did not match; nothing stopped.' }
    if ($kind -eq 'web' -and $service.CommandLine -notlike '*8503*') { throw 'Wrong web instance; nothing stopped.' }
    $targets+=$serviceId
}
foreach ($serviceId in $targets) { Stop-Process -Id $serviceId }
$python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$helper=Join-Path $PSScriptRoot 'public_host.py'
$runtime=Join-Path $PSScriptRoot 'runtime\public'
$next=Start-Process -FilePath $python -ArgumentList ('"'+$helper+'" --reuse-tunnel') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'supervisor.log') -RedirectStandardError (Join-Path $runtime 'supervisor-error.log')
$deadline=(Get-Date).AddSeconds(50)
do {
    Start-Sleep -Milliseconds 400
    $current=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    # A Windows venv launcher may create a child interpreter with a different PID.
    if ($current.supervisor_pid -ne $state.supervisor_pid -and $current.phase -eq 'ready') {
        $owner=Get-CimInstance Win32_Process -Filter "ProcessId = $($current.supervisor_pid)"
        if ($owner.CommandLine -notlike ('*'+$helper+'*')) { throw 'Reload owner did not match.' }
        Write-Output ('Reloaded without changing URL: '+$current.url); exit 0
    }
    if ($next.HasExited) { throw 'Reload failed; see runtime\public\supervisor-error.log' }
} while ((Get-Date) -lt $deadline)
throw 'Reload timed out; see runtime\public logs'
