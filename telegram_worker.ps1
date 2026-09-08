$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$runtimePath = Join-Path $PSScriptRoot '.runtime'
[System.IO.Directory]::CreateDirectory($runtimePath) | Out-Null
$workerLock = $null
try {
    try {
        $workerLock = [System.IO.File]::Open((Join-Path $runtimePath 'telegram-worker.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch [System.IO.IOException] {
        exit 0
    }
    & python -B (Join-Path $PSScriptRoot 'src/telegram_worker.py')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    if ($workerLock) { $workerLock.Dispose() }
}
