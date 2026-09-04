[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$log = Join-Path $repo "refresh_log.txt"
$previousLog = Join-Path $repo "refresh_log.previous.txt"
$maxLogBytes = 2MB
$mutex = [System.Threading.Mutex]::new($false, "Global\SharpieDashboardAutoPublish")
$hasLock = $false
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)

function Invoke-NativeLogged {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @(),
        [ConsoleColor]$Color = "Gray"
    )

    # Windows PowerShell convierte stderr de programas nativos en ErrorRecord.
    # Una advertencia de Git no debe abortar si el proceso terminó con código 0.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $FilePath @Arguments 2>&1 | ForEach-Object {
            Write-Utf8Log ([string]$_) $Color
        }
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Invoke-NativeQuiet {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $FilePath @Arguments *> $null
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

try {
    $hasLock = $mutex.WaitOne(0)
    if (-not $hasLock) {
        Write-Host "[INFO] Ya existe otra ejecución de Sharpie en curso." -ForegroundColor Yellow
        exit 0
    }

    if ((Test-Path $log) -and (Get-Item $log).Length -ge $maxLogBytes) {
        Move-Item $log $previousLog -Force
    }

    chcp 65001 | Out-Null
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    [Console]::InputEncoding = $utf8NoBom
    [Console]::OutputEncoding = $utf8NoBom
    $OutputEncoding = $utf8NoBom
    Set-Location $repo

    function Write-Utf8Log {
        param([AllowEmptyString()][string]$Text, [ConsoleColor]$Color = "White")
        if ($Text) {
            Write-Host $Text -ForegroundColor $Color
        }
        [System.IO.File]::AppendAllLines(
            $log,
            [string[]]@($Text),
            $utf8NoBom
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
    $pythonExitCode = Invoke-NativeLogged `
        -FilePath $pythonExe `
        -Arguments @("-B", "src\main.py")
    if ($pythonExitCode -ne 0) {
        throw "main.py finalizó con código $pythonExitCode"
    }

    Write-TrackStep 2 "Preparación controlada de archivos"
    $publishPaths = @(
        ".gitignore",
        ".gitattributes",
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

    $gitAddCode = Invoke-NativeLogged `
        -FilePath "git" `
        -Arguments (@("add", "--") + $publishPaths)
    if ($gitAddCode -ne 0) {
        throw "git add falló con código $gitAddCode"
    }

    $gitDiffCode = Invoke-NativeQuiet `
        -FilePath "git" `
        -Arguments @("diff", "--cached", "--quiet")
    if ($gitDiffCode -eq 0) {
        Write-Utf8Log "[INFO] No existen cambios para publicar." Yellow
        exit 0
    }
    if ($gitDiffCode -ne 1) {
        throw "No se pudo verificar el área de stage."
    }

    Write-TrackStep 3 "Creación del commit"
    $commitMsg = "Auto-update Sharpie ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
    $gitCommitCode = Invoke-NativeLogged `
        -FilePath "git" `
        -Arguments @("commit", "-m", $commitMsg)
    if ($gitCommitCode -ne 0) {
        throw "git commit falló con código $gitCommitCode"
    }

    Write-TrackStep 4 "Publicación en GitHub"
    $gitPushCode = Invoke-NativeLogged `
        -FilePath "git" `
        -Arguments @("push", "origin", "main", "--quiet")
    if ($gitPushCode -ne 0) {
        throw "git push falló con código $gitPushCode"
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
            $utf8NoBom
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
