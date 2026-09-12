param([switch]$SkipPublish)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$log = Join-Path $repo 'refresh_log.txt'
$env:PYTHONIOENCODING = 'utf-8'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Set-Location -LiteralPath $repo

function Write-RunLog([string]$Message) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Write-Host $line
    [System.IO.File]::AppendAllText($log, $line + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
}

function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments 2>&1 | ForEach-Object { Write-RunLog ([string]$_) }
    if ($LASTEXITCODE -ne 0) {
        throw "$Program fallo con codigo $LASTEXITCODE"
    }
}

$runLock = $null
try {
    try {
        $runLock = [System.IO.File]::Open((Join-Path $repo '.pipeline.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch [System.IO.IOException] {
        Write-RunLog 'Ya hay una actualizacion en curso; ejecucion omitida.'
        exit 0
    }

    if (-not $SkipPublish) {
        $changes = @(& git status --porcelain --untracked-files=all)
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar Git' }
        $sourceChanges = @($changes | Where-Object {
            $_.Substring(3) -notmatch '^(index\.html|opportunities\.html|picks\.json|dashboard-version\.json|data/parsed/[^/]+\.json|data/analyzed/sharpie\.json|data/opportunities\.json)$'
        })
        if ($sourceChanges.Count -gt 0) {
            Write-RunLog 'Cambios locales pendientes de revision; se actualizan los registros localmente sin publicar.'
            $SkipPublish = $true
        }
    }

    Write-RunLog 'Iniciando descarga, parseo, analisis y dashboard.'
    Invoke-Checked -Program 'python' -Arguments @('-B', 'src/main.py')
    if ($SkipPublish) {
        Write-RunLog 'Dashboard actualizado localmente.'
        exit 0
    }

    Invoke-Checked -Program 'git' -Arguments @('add', '--', 'index.html', 'opportunities.html', 'picks.json', 'dashboard-version.json', 'data/parsed', 'data/analyzed', 'data/opportunities.json')
    & git diff --cached --quiet
    $diffStatus = $LASTEXITCODE
    if ($diffStatus -gt 1) { throw 'No se pudieron comprobar los cambios preparados' }
    if ($diffStatus -eq 1) {
        $message = 'Auto-update: Dashboard actual ({0})' -f (Get-Date -Format 'yyyy-MM-dd HH:mm')
        Invoke-Checked -Program 'git' -Arguments @('commit', '-m', $message)
    }
    Invoke-Checked -Program 'git' -Arguments @('push', 'origin', 'main', '--quiet')
    Invoke-Checked -Program 'python' -Arguments @('-B', 'src/publish_opportunities.py')
    Invoke-Checked -Program 'git' -Arguments @('add', '--', 'opportunities.html', 'data/opportunities.json')
    & git diff --cached --quiet
    $archiveDiff = $LASTEXITCODE
    if ($archiveDiff -gt 1) { throw 'No se pudo comprobar el archivo de oportunidades' }
    if ($archiveDiff -eq 1) {
        Invoke-Checked -Program 'git' -Arguments @('commit', '-m', 'Archive opportunities from verified public dashboard')
        Invoke-Checked -Program 'git' -Arguments @('push', 'origin', 'main', '--quiet')
    }
    Write-RunLog 'Dashboard actualizado y publicado correctamente.'
} catch {
    Write-RunLog ('ERROR: ' + $_.Exception.Message)
    exit 1
} finally {
    if ($null -ne $runLock) { $runLock.Dispose() }
}
