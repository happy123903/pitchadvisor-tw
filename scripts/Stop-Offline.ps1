$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot '.cache\offline-server.json'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'No owned offline server record.'; exit 0 }
$record = Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($record.root -ne $projectRoot) { throw 'The offline record belongs to a different project.' }
$instance = [string]$record.instance_id
if ($instance -notmatch '^[0-9a-fA-F-]{36}$') { throw 'Invalid offline ownership token.' }
$scriptPath = (Join-Path $PSScriptRoot 'serve_offline.py').Replace('/','\')
# Windows venv launchers may spawn another python.exe. Match the unique instance
# token AND absolute script path, rather than trusting a reusable saved PID.
$owned = @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
    $command = ([string]$_.CommandLine).Replace('/','\')
    $command.IndexOf($scriptPath,[System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
    $command.IndexOf($instance,[System.StringComparison]::OrdinalIgnoreCase) -ge 0
})
# Kill the actual serving child before its venv launcher.
$owned = @($owned | Sort-Object @{Expression={if ($_.ProcessId -eq $record.launcher_pid) { 1 } else { 0 }}})
foreach ($processInfo in $owned) {
    $current = Get-CimInstance Win32_Process -Filter "ProcessId = $($processInfo.ProcessId)" -ErrorAction SilentlyContinue
    if ($current -and $current.CreationDate -eq $processInfo.CreationDate -and $current.CommandLine -eq $processInfo.CommandLine) {
        Stop-Process -Id $processInfo.ProcessId -ErrorAction SilentlyContinue
    }
}
Remove-Item -LiteralPath $pidFile
Write-Output "Stopped $($owned.Count) owned offline Python process(es)."
