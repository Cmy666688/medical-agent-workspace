param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$runtime = Join-Path $PSScriptRoot 'runtime'
$health = 'http://127.0.0.1:8502/_stcore/health'
$url = 'http://localhost:8502/account'
$mutex = New-Object System.Threading.Mutex($false, 'Local\MedicalWorkspace8502Launcher')
$locked = $false
try {
    try { $locked = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $locked = $true }
    if (-not $locked) { Write-Host 'The application is already starting.'; exit 0 }
    if (-not (Test-Path -LiteralPath $python)) { throw 'Missing .venv\Scripts\python.exe. Restore the project Python environment first.' }
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    $listener = Get-NetTCPConnection -LocalPort 8502 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)"
        if ($existing.CommandLine -notlike '*znt*' -or $existing.CommandLine -notlike '*streamlit*' -or $existing.CommandLine -notlike '*8502*') {
            throw 'Port 8502 is in use by another application. It has not been stopped.'
        }
        Write-Host 'The web service is already running.'
    } else {
        Write-Host 'Starting the medical workspace...'
        $arguments = '-m streamlit run "' + (Join-Path $PSScriptRoot 'app.py') + '" --server.port 8502'
        $server = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtime 'server.log') -RedirectStandardError (Join-Path $runtime 'server-error.log')
    }
    $workerPath = Join-Path $PSScriptRoot 'reminder_worker.py'
    $workers = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -like "*$workerPath*" -and $_.CommandLine -notlike '*--runtime-profile public*' }
    if (-not $workers) {
        Start-Process -FilePath $python -ArgumentList ('"' + $workerPath + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'reminder.log') -RedirectStandardError (Join-Path $runtime 'reminder-error.log')
    }
    $deadline = (Get-Date).AddSeconds(40)
    $ready = $false
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $health -TimeoutSec 2
            $ready = $response.StatusCode -eq 200 -and $response.Content.Trim() -eq 'ok'
        } catch { }
        if (-not $ready) {
            if ($server -and $server.HasExited) { throw "The web service exited. Check $runtime\server-error.log" }
            Start-Sleep -Milliseconds 300
        }
    } while (-not $ready -and (Get-Date) -lt $deadline)
    if (-not $ready) { throw "The web service did not become ready. Check $runtime\server-error.log" }
    Write-Host "Ready: $url"
    Write-Host 'The web service and reminder worker continue running after this launcher closes.'
    if (-not $NoBrowser) { Start-Process $url }
} catch {
    Write-Host ('Startup failed: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
