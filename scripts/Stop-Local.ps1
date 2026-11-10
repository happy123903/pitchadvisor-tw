$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $projectRoot '.cache\local-servers.json'
if (-not (Test-Path -LiteralPath $pidFile)) { Write-Output 'No owned local server record.'; exit 0 }
$record = Get-Content -LiteralPath $pidFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ($record.root -ne $projectRoot) { throw 'Server record belongs to a different project.' }
$ownedProcesses = @()
$pendingIds = @($record.api_pid,$record.web_pid)
while ($pendingIds.Count -gt 0) {
    $processId = $pendingIds[0]
    $pendingIds = @($pendingIds | Select-Object -Skip 1)
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($processInfo) {
        # Console hosts have no project command line; they exit with their owner.
        if ($processInfo.Name -eq 'conhost.exe') { continue }
        $normalizedCommand = ([string]$processInfo.CommandLine).Replace('/','\')
        if ($normalizedCommand.IndexOf($projectRoot,[System.StringComparison]::OrdinalIgnoreCase) -lt 0) { throw "PID $processId no longer belongs to this project; refusing to stop it." }
        $ownedProcesses += $processId
        $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $processId" -ErrorAction SilentlyContinue)
        $pendingIds += @($children | ForEach-Object ProcessId)
    }
}
# Stop deepest children before launchers (venv on Windows may spawn real Python).
[array]::Reverse($ownedProcesses)
foreach ($processId in $ownedProcesses) {
    Stop-Process -Id $processId -ErrorAction SilentlyContinue
}
Remove-Item -LiteralPath $pidFile
Write-Output 'Stopped owned PitchAdvisor services.'
