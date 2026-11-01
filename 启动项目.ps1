param([switch]$NoBrowser)
& (Join-Path $PSScriptRoot 'start_app.ps1') -NoBrowser:$NoBrowser
