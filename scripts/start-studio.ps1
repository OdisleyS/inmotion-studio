$studioRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$backendPython = Join-Path $studioRoot ".venv\Scripts\python.exe"
$frontendRoot = Join-Path $studioRoot "frontend-ts"

function Test-StudioPort([int] $port) {
    $connection = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    return $null -ne $connection
}

if (-not (Test-StudioPort 8000)) {
    Start-Process -WindowStyle Hidden -FilePath $backendPython -WorkingDirectory $studioRoot -ArgumentList @(
        "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000", "--env-file", ".env"
    ) | Out-Null
}

if (-not (Test-StudioPort 4174)) {
    Start-Process -WindowStyle Hidden -FilePath "npm.cmd" -WorkingDirectory $frontendRoot -ArgumentList @("run", "dev:host") | Out-Null
}

Write-Host "In-House Video Studio: http://127.0.0.1:4174/"
Write-Host "Backend: http://127.0.0.1:8000/"
