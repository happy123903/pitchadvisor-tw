param([int]$ApiPort = 8000, [int]$WebPort = 5173)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$viteEntry = Join-Path $projectRoot 'web\node_modules\vite\bin\vite.js'
$cachePath = Join-Path $projectRoot '.cache'
New-Item -ItemType Directory -Path $cachePath -Force | Out-Null
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run uv sync first (see README.md).' }
if (-not (Test-Path -LiteralPath $viteEntry)) { throw 'Run npm install in web first.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'artifacts\week2\manifest.json'))) { throw 'Restore the committed week-two artifact or build it first (see README.md).' }
$pidFile = Join-Path $cachePath 'local-servers.json'
if (Test-Path -LiteralPath $pidFile) { throw 'A local server record already exists. Run Stop-Local.ps1 before restarting.' }
$api = Start-Process -FilePath $pythonExe -ArgumentList @('-m','uvicorn','api.main:app','--app-dir',('"'+$projectRoot+'"'),'--host','127.0.0.1','--port',"$ApiPort") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $cachePath 'api.stdout.log') -RedirectStandardError (Join-Path $cachePath 'api.stderr.log') -PassThru
$web = Start-Process -FilePath (Get-Command node.exe).Source -ArgumentList @(('"'+$viteEntry+'"'),'--host','127.0.0.1','--port',"$WebPort",'--strictPort') -WorkingDirectory (Join-Path $projectRoot 'web') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $cachePath 'web.stdout.log') -RedirectStandardError (Join-Path $cachePath 'web.stderr.log') -PassThru
@{ api_pid=$api.Id; web_pid=$web.Id; api_port=$ApiPort; web_port=$WebPort; root=$projectRoot } | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
Write-Output "Frontend: http://127.0.0.1:$WebPort"
Write-Output "API docs: http://127.0.0.1:$ApiPort/docs"
Write-Output 'Use scripts/Stop-Local.ps1 to stop only these project processes.'
