param([switch]$NoBrowser)
$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtime=Join-Path $PSScriptRoot 'runtime\public'
$statePath=Join-Path $runtime 'hosting.json'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$mutex=New-Object System.Threading.Mutex($false,'Local\MedicalPublic8503Launcher')
$locked=$false
try {
    try { $locked=$mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $locked=$true }
    if (-not $locked) { throw 'The public service is already starting.' }
    $running=$false
    if (Test-Path -LiteralPath $statePath) {
        $state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $owner=Get-CimInstance Win32_Process -Filter "ProcessId = $($state.supervisor_pid)" -ErrorAction SilentlyContinue
        $running=$owner -and $owner.CommandLine -like ('*'+(Join-Path $PSScriptRoot 'public_host.py')+'*')
    }
    if (-not $running) {
        $listener=Get-NetTCPConnection -LocalPort 8503 -State Listen -ErrorAction SilentlyContinue
        if ($listener) { throw 'Port 8503 is in use. No existing process has been stopped.' }
        if (Test-Path -LiteralPath $statePath) { Remove-Item -LiteralPath $statePath }
        $python=Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
        $helper=Join-Path $PSScriptRoot 'public_host.py'
        Start-Process -FilePath $python -ArgumentList ('"'+$helper+'"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'supervisor.log') -RedirectStandardError (Join-Path $runtime 'supervisor-error.log')
    }
    $deadline=(Get-Date).AddSeconds(100)
    do {
        Start-Sleep -Milliseconds 400
        if (Test-Path -LiteralPath $statePath) {
            $state=Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            if ($state.phase -eq 'ready') { break }
            if ($state.phase -eq 'stopped') { throw $state.error }
        }
    } while ((Get-Date) -lt $deadline)
    if ($state.phase -ne 'ready') { throw 'Public startup timed out. See runtime\public logs.' }
    Write-Host ('Public URL: '+$state.url+'/account')
    Write-Host 'This URL stays available while this computer and its public services are running.'
    Write-Host 'Public accounts and family records are separate from the local workspace.'
    if (-not $NoBrowser) { Start-Process ($state.url+'/account') }
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
