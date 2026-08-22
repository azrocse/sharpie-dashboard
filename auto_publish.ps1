# 0. Ocultar la ventana automáticamente si se abrió visible
if ([Environment]::UserInteractive -and -not $env:PS_HIDDEN) {
    $env:PS_HIDDEN = "1"
    Start-Process powershell.exe -ArgumentList "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$PSCommandPath`"" -WindowStyle Hidden
    exit
}

$repo = "C:\Users\Administrator\Desktop\sharpie-dashboard"
$log  = "$repo\refresh_log.txt"

# 1. Configuración de entorno y codificación segura para entornos en segundo plano
$env:PYTHONIOENCODING = "utf-8"
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

Set-Location $repo

# Función optimizada y protegida contra salidas vacías o nulas
function Write-Utf8Log ($text) {
    if ($null -eq $text -or $text -eq "") { 
        $text = [string]::Empty 
    }
    [System.IO.File]::AppendAllLines($log, [string[]]$text, [System.Text.Encoding]::UTF8)
}

# Nueva función auxiliar para separar visualmente los procesos en el log
function Write-TrackStep ($stepNumber, $stepName) {
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Utf8Log "------------------------------------------------------------"
    Write-Utf8Log "[$timestamp] [STEP $stepNumber/4] EJECUTANDO: $stepName"
    Write-Utf8Log "------------------------------------------------------------"
}

# --- INICIO DEL PROCESO ---
Write-Utf8Log "============================================================"
Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] INICIANDO SCRIPT DE AUTO-PUBLICACIÓN"
Write-Utf8Log "============================================================"

# STEP 1: EJECUCIÓN DEL SCRIPT DE PYTHON
Write-TrackStep "1" "Script de Python (src\main.py)"
$pythonOutput = & python -B src\main.py 2>&1
Write-Utf8Log $pythonOutput

if ($LASTEXITCODE -eq 0) {
    Write-Utf8Log "[SUCCESS] Python finalizó correctamente con código de salida 0."

    # STEP 2: GIT ADD
    Write-TrackStep "2" "Rastreo de cambios en Git (git add -A)"
    $gitAddOutput = & git add -A 2>&1
    Write-Utf8Log $gitAddOutput
    Write-Utf8Log "[INFO] Archivos preparados en el área de stage."
    
    # STEP 3: GIT COMMIT
    Write-TrackStep "3" "Creación de Commit descriptivo (git commit)"
    $commitMsg = "Auto-update: Datos, scripts y assets ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
    $gitCommitOutput = & git commit -m $commitMsg 2>&1
    Write-Utf8Log $gitCommitOutput
    
    # STEP 4: GIT PUSH
    Write-TrackStep "4" "Sincronización con GitHub (git push)"
    $gitPushOutput = & git push origin main --quiet 2>&1
    Write-Utf8Log $gitPushOutput
    
    Write-Utf8Log "============================================================"
    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] PROCESO FINALIZADO: Todo se actualizó y publicó con éxito."
    Write-Utf8Log "============================================================`n"
} else {
    Write-Utf8Log "============================================================"
    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR CRÍTICO: main.py falló (Código de salida $LASTEXITCODE)."
    Write-Utf8Log "[INFO] Proceso de Git abortado para proteger la consistencia del repositorio."
    Write-Utf8Log "============================================================`n"
}
