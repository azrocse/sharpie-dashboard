[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$log = Join-Path $repo "refresh_log.txt"
$previousLog = Join-Path $repo "refresh_log.previous.txt"
$maxLogBytes = 2MB
$mutex = [System.Threading.Mutex]::new($false, "Global\SharpieDashboardAutoPublish")
$hasLock = $false

try {
    $hasLock = $mutex.WaitOne(0)
    if (-not $hasLock) {
        Write-Host "[INFO] Ya existe otra ejecución de Sharpie en curso." -ForegroundColor Yellow
        exit 0
    }

    if ((Test-Path $log) -and (Get-Item $log).Length -ge $maxLogBytes) {
        Move-Item $log $previousLog -Force
    }

    $env:PYTHONIOENCODING = "utf-8"
    $OutputEncoding = [System.Text.Encoding]::UTF8
    chcp 65001 | Out-Null
    Set-Location $repo

    function Write-Utf8Log {
        param([AllowEmptyString()][string]$Text, [ConsoleColor]$Color = "White")
        if ($Text) {
            Write-Host $Text -ForegroundColor $Color
        }
        [System.IO.File]::AppendAllLines(
            $log,
            [string[]]@($Text),
            [System.Text.UTF8Encoding]::new($false)
        )
    }

    function Write-TrackStep {
        param([int]$Number, [string]$Name)
        $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Utf8Log "------------------------------------------------------------" Cyan
        Write-Utf8Log "[$timestamp] [PASO $Number/4] $Name" Cyan
        Write-Utf8Log "------------------------------------------------------------" Cyan
    }

    Write-Utf8Log "============================================================" Magenta
    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] INICIANDO SHARPIE" Magenta

    $configuredPython = "C:\Program Files\PyManager\python.exe"
    if (Test-Path $configuredPython) {
        $pythonExe = $configuredPython
    } else {
        $pythonExe = (Get-Command python -ErrorAction Stop).Source
    }

    Write-TrackStep 1 "Ejecución del pipeline"
    & $pythonExe -B "src\main.py" 2>&1 | ForEach-Object {
        Write-Utf8Log ([string]$_) Gray
    }
    $pythonExitCode = $LASTEXITCODE
    if ($pythonExitCode -ne 0) {
        throw "main.py finalizó con código $pythonExitCode"
    }

    Write-TrackStep 2 "Preparación controlada de archivos"
    $publishPaths = @(
        ".gitignore",
        "auto_publish.ps1",
        "cleanup_once.ps1",
        "cleanup_once.cmd",
        "git_audit.ps1",
        "untrack_runtime_data.cmd",
        "OPTIMIZACION.md",
        "src",
        "index.html",
        "picks.json",
        "results.html"
    ) | Where-Object { Test-Path (Join-Path $repo $_) }

    & git add -- $publishPaths 2>&1 | ForEach-Object {
        Write-Utf8Log ([string]$_) Gray
    }
    if ($LASTEXITCODE -ne 0) {
        throw "git add falló con código $LASTEXITCODE"
    }

    & git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        Write-Utf8Log "[INFO] No existen cambios para publicar." Yellow
        exit 0
    }
    if ($LASTEXITCODE -ne 1) {
        throw "No se pudo verificar el área de stage."
    }

    Write-TrackStep 3 "Creación del commit"
    $commitMsg = "Auto-update Sharpie ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
    & git commit -m $commitMsg 2>&1 | ForEach-Object {
        Write-Utf8Log ([string]$_) Gray
    }
    if ($LASTEXITCODE -ne 0) {
        throw "git commit falló con código $LASTEXITCODE"
    }

    Write-TrackStep 4 "Publicación en GitHub"
    & git push origin main --quiet 2>&1 | ForEach-Object {
        Write-Utf8Log ([string]$_) Gray
    }
    if ($LASTEXITCODE -ne 0) {
        throw "git push falló con código $LASTEXITCODE"
    }

    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] PUBLICACIÓN COMPLETADA" Green
    Write-Utf8Log "============================================================" Green
}
catch {
    $message = $_.Exception.Message
    Write-Host "[ERROR] $message" -ForegroundColor Red
    try {
        [System.IO.File]::AppendAllLines(
            $log,
            [string[]]@("[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [ERROR] $message"),
            [System.Text.UTF8Encoding]::new($false)
        )
    } catch {}
    exit 1
}
finally {
    if ($hasLock) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
