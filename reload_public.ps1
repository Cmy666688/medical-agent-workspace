$ErrorActionPreference='Stop'
$statePath=Join-Path $PSScriptRoot 'runtime\public\hosting.json'
$state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
$targets=@()
foreach ($kind in @('supervisor','web','worker')) {
    $serviceId=$state.($kind+'_pid')
    $service=Get-CimInstance Win32_Process -Filter "ProcessId = $serviceId"
    $expected=switch ($kind) { 'supervisor' { Join-Path $PSScriptRoot 'public_host.py' } 'web' { Join-Path $PSScriptRoot 'app.py' } 'worker' { Join-Path $PSScriptRoot 'reminder_worker.py' } }
    if (-not $service -or $service.CommandLine -notlike ('*'+$expected+'*')) { throw 'Existing public process did not match; nothing stopped.' }
    if ($kind -eq 'web' -and $service.CommandLine -notlike '*8503*') { throw 'Wrong web instance; nothing stopped.' }
    if ($kind -eq 'worker' -and $service.CommandLine -notlike '*--runtime-profile public*') { throw 'Wrong worker instance; nothing stopped.' }
    $targets+=$serviceId
}
# Windows virtualenv launchers create a child interpreter. Verify the entire
# recorded subtree before stopping it, while leaving cloudflared attached.
$snapshot=@(Get-CimInstance Win32_Process)
$pending=@($targets)
while ($pending.Count -gt 0) {
    $parentId=$pending[0]
    $pending=@($pending | Select-Object -Skip 1)
    foreach ($child in $snapshot | Where-Object { $_.ParentProcessId -eq $parentId -and $_.ProcessId -notin $targets -and $_.ProcessId -ne $state.tunnel_pid }) {
        # Windows may attach its own console host to a hidden Python process.
        # It exits with the console; never treat it as an application to kill.
        if ($child.Name -eq 'conhost.exe' -and $child.ExecutablePath -eq (Join-Path $env:WINDIR 'System32\conhost.exe')) { continue }
        $valid=$child.Name -eq 'python.exe' -and (
            ($child.CommandLine -like ('*'+(Join-Path $PSScriptRoot 'app.py')+'*') -and $child.CommandLine -like '*8503*') -or
            ($child.CommandLine -like ('*'+(Join-Path $PSScriptRoot 'reminder_worker.py')+'*') -and $child.CommandLine -like '*--runtime-profile public*'))
        if (-not $valid) { throw 'Unexpected child of a public service; nothing stopped.' }
        $targets+=$child.ProcessId
        $pending+=$child.ProcessId
    }
}
foreach ($serviceId in $targets) { Stop-Process -Id $serviceId -ErrorAction SilentlyContinue }
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
