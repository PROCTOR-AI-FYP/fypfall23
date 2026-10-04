param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeDir = Join-Path $projectRoot 'ai-engine/.runtime/local-web'
$mediaTools = Join-Path $projectRoot 'ai-engine/.runtime/tools'
if (Test-Path -LiteralPath (Join-Path $mediaTools 'ffmpeg.exe')) { $env:PATH = "$mediaTools;$env:PATH" }
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

function Test-LocalEndpoint([string]$Address) {
    try {
        $reply = Invoke-WebRequest -Uri $Address -TimeoutSec 2 -UseBasicParsing
        return $reply.StatusCode -eq 200
    } catch { return $false }
}

$pidFile = Join-Path $runtimeDir 'servers.json'
$servers = if (Test-Path -LiteralPath $pidFile) {
    Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json -AsHashtable
} else { @{} }
if (-not (Test-LocalEndpoint 'http://127.0.0.1:8000/healthz')) {
    $pythonPath = Join-Path $projectRoot 'venv/Scripts/python.exe'
    $env:LOCAL_CAMERA_ENABLED = 'true'
    # Preserve configured origins and allow both exact loopback addresses.
    $env:CORS_ALLOWED_ORIGINS = & $pythonPath -c "import os,sys; from dotenv import dotenv_values; configured=os.environ.get('CORS_ALLOWED_ORIGINS',dotenv_values(sys.argv[1]).get('CORS_ALLOWED_ORIGINS','')); origins=[s.strip().rstrip('/') for s in configured.split(',') if s.strip()]; origins+=['http://127.0.0.1:5173','http://localhost:5173','http://127.0.0.1:4173','http://localhost:4173']; print(','.join(dict.fromkeys(origins)))" (Join-Path $projectRoot 'backend/.env')
    $backend = Start-Process -FilePath $pythonPath -ArgumentList @('-X', 'faulthandler', '-u', '-m', 'uvicorn', 'app.main:asgi_app', '--host', '127.0.0.1', '--port', '8000', '--loop', 'asyncio', '--http', 'h11') -WorkingDirectory (Join-Path $projectRoot 'backend') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'backend.out.log') -RedirectStandardError (Join-Path $runtimeDir 'backend.err.log') -PassThru
    $servers.backend = $backend.Id
}
if (-not (Test-LocalEndpoint 'http://127.0.0.1:5173/')) {
    $nodePath = (Get-Command node -ErrorAction Stop).Source
    $vitePath = Join-Path $projectRoot 'node_modules/vite/bin/vite.js'
    $frontend = Start-Process -FilePath $nodePath -ArgumentList @($vitePath, '--host', '127.0.0.1', '--port', '5173', '--strictPort') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'frontend.out.log') -RedirectStandardError (Join-Path $runtimeDir 'frontend.err.log') -PassThru
    $servers.frontend = $frontend.Id
}
$servers | ConvertTo-Json | Set-Content -LiteralPath $pidFile
Write-Output 'ProctorAI: http://127.0.0.1:5173/'
Write-Output "Logs: $runtimeDir"
