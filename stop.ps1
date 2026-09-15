# Stops whatever is serving the backend (8000) and frontend (5173).
#
# Kills the listening process and its parent, because uvicorn's --reload runs
# as a reloader parent plus a worker child: killing only the worker makes the
# reloader spawn a replacement, and killing only the parent leaves the worker
# orphaned but still holding the port -- which is exactly the state that kept
# turning up during development.

$ErrorActionPreference = "SilentlyContinue"

# One pass is not enough. uvicorn's reloader immediately spawns a replacement
# worker whenever the current one dies, so a single kill-then-check races the
# respawn and routinely leaves the port held -- which is how a "stopped"
# backend kept coming back during development, serving stale code that looked
# like a reload had failed. Kill the parent first so nothing is left to
# respawn, then keep going until the port is genuinely free.
foreach ($port in 8000, 5173) {
    $stopped = $false
    for ($attempt = 1; $attempt -le 6; $attempt++) {
        $connection = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if (-not $connection) {
            if ($attempt -eq 1) { Write-Host "$port : nem fut semmi." } else { Write-Host "$port : leallitva." }
            $stopped = $true
            break
        }
        $processId = $connection.OwningProcess
        $parentId = (Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue).ParentProcessId
        if ($parentId -and $parentId -ne 0) { Stop-Process -Id $parentId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
    if (-not $stopped) {
        Write-Host "$port : NEM sikerult leallitani, meg mindig foglalt." -ForegroundColor Red
    }
}
