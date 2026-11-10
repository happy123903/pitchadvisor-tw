$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$record = Get-Content -LiteralPath (Join-Path $projectRoot '.cache\local-servers.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$measurements = @()
foreach ($role in @('api','web')) {
    $processId = if ($role -eq 'api') { $record.api_pid } else { $record.web_pid }
    $candidates = @($processId)
    if ($role -eq 'api') {
        $candidates += @(Get-CimInstance Win32_Process -Filter "ParentProcessId = $processId" | ForEach-Object ProcessId)
    }
    foreach ($candidateId in $candidates) {
        $processInfo = Get-Process -Id $candidateId -ErrorAction SilentlyContinue
        if ($processInfo) {
            $measurements += @{ role=$role; pid=$candidateId; process=$processInfo.ProcessName; working_set_bytes=$processInfo.WorkingSet64; peak_working_set_bytes=$processInfo.PeakWorkingSet64 }
        }
    }
}
@{ measurement='Local process working set; API includes Windows venv launcher and child; not Render measurements'; processes=$measurements } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $projectRoot 'docs\week1\local_process_memory.json') -Encoding UTF8
$measurements | Format-Table
