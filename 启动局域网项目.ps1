Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONIOENCODING='utf-8'
New-Item -ItemType Directory -Force -Path "$PSScriptRoot\runtime" | Out-Null
Start-Process -FilePath "$PSScriptRoot\.venv\Scripts\python.exe" -ArgumentList "`"$PSScriptRoot\reminder_worker.py`"" -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput "$PSScriptRoot\runtime\reminder.log" -RedirectStandardError "$PSScriptRoot\runtime\reminder-error.log"
Write-Host '同一可信局域网成员可通过 本机内网IP:8502 访问。相机功能在远程浏览器需要 HTTPS。'
& "$PSScriptRoot\.venv\Scripts\python.exe" -m streamlit run "$PSScriptRoot\app.py" --server.port 8502 --server.address 0.0.0.0
