param([string]$PythonExe = '', [int]$Port = 8765, [string]$WebDir = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $PythonExe) { $PythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) { throw 'Provide -PythonExe pointing to Python 3.12 with the runtime dependencies already installed.' }
$pythonPath = (Resolve-Path -LiteralPath $PythonExe).Path
$serverScript = Join-Path $PSScriptRoot 'serve_offline.py'
$cachePath = Join-Path $projectRoot '.cache'
New-Item -ItemType Directory -Path $cachePath -Force | Out-Null
$pidFile = Join-Path $cachePath 'offline-server.json'
if (Test-Path -LiteralPath $pidFile) { throw 'An offline process record exists. Run scripts/Stop-Offline.ps1 before restarting.' }
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Port must be between 1 and 65535.' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "Port $Port is already in use." }
$instance = [Guid]::NewGuid().ToString()
$arguments = @('-X','utf8',('"'+$serverScript+'"'),'--port',"$Port",'--instance-id',$instance)
if ($WebDir) { $arguments += @('--web-dir',('"'+(Resolve-Path -LiteralPath $WebDir).Path+'"')) }
$process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $cachePath 'offline.stdout.log') -RedirectStandardError (Join-Path $cachePath 'offline.stderr.log') -PassThru
$record = @{ root=$projectRoot; instance_id=$instance; launcher_pid=$process.Id; port=$Port; started_utc=[DateTime]::UtcNow.ToString('o') }
$record | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
$ready = $false
for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
        $info = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/offline-info" -TimeoutSec 1
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 1
        if ($info.instance_id -eq $instance -and $health.status -eq 'ready' -and $health.data_source -eq 'local_snapshot') {
            $record.server_pid = $info.server_pid
            $record | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8
            $ready = $true
            break
        }
    } catch { }
    Start-Sleep -Milliseconds 500
}
if (-not $ready) {
    & (Join-Path $PSScriptRoot 'Stop-Offline.ps1')
    throw 'Offline startup did not become ready. Check .cache/offline.stderr.log.'
}
Write-Output "Offline frontend and API: http://127.0.0.1:$Port/"
Write-Output "Actual inference process: $($record.server_pid)"
Write-Output 'No cloud credentials are loaded. Use scripts/Stop-Offline.ps1 to stop this instance.'
