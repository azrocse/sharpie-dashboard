# 0. Ventana visible para ver el proceso en consola
# (Se ha desactivado el modo oculto para que puedas monitorear todo en vivo)

$repo = "C:\Users\Administrator\Desktop\sharpie-dashboard"
$log  = "$repo\refresh_log.txt"

# 1. Configuración de entorno y codificación segura
$env:PYTHONIOENCODING = "utf-8"
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

Set-Location $repo

# Función que escribe en el archivo y ADEMÁS muestra el texto en la consola
function Write-Utf8Log ($text, $color = "White") {
    if ($null -eq $text -or $text -eq "") { 
        $text = [string]::Empty 
    } else {
        # Muestra el texto en la consola de PowerShell con el color elegido
        Write-Host $text -ForegroundColor $color
    }
    [System.IO.File]::AppendAllLines($log, [string[]]$text, [System.Text.Encoding]::UTF8)
}

# Función auxiliar para separar visualmente los procesos en consola y log
function Write-TrackStep ($stepNumber, $stepName) {
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Utf8Log "------------------------------------------------------------" "Cyan"
    Write-Utf8Log "[$timestamp] [STEP $stepNumber/4] EJECUTANDO: $stepName" "Cyan"
    Write-Utf8Log "------------------------------------------------------------" "Cyan"
}

# --- INICIO DEL PROCESO ---
Write-Utf8Log "============================================================" "Magenta"
Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] INICIANDO SCRIPT DE AUTO-PUBLICACIÓN" "Magenta"
Write-Utf8Log "============================================================" "Magenta"

# STEP 1: EJECUCIÓN DEL SCRIPT DE PYTHON
Write-TrackStep "1" "Script de Python (src\main.py)"
$pythonOutput = & python -B src\main.py 2>&1
Write-Utf8Log $pythonOutput "Gray"

if ($LASTEXITCODE -eq 0) {
    Write-Utf8Log "[SUCCESS] Python finalizó correctamente con código de salida 0." "Green"

    # STEP 2: GIT ADD
    Write-TrackStep "2" "Rastreo de cambios en Git (git add -A)"
    $gitAddOutput = & git add -A 2>&1
    Write-Utf8Log $gitAddOutput "Gray"
    Write-Utf8Log "[INFO] Archivos preparados en el área de stage." "Yellow"
    
    # STEP 3: GIT COMMIT
    Write-TrackStep "3" "Creación de Commit descriptivo (git commit)"
    $commitMsg = "Auto-update: Datos, scripts y assets ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
    $gitCommitOutput = & git commit -m $commitMsg 2>&1
    Write-Utf8Log $gitCommitOutput "Gray"
    
    # STEP 4: GIT PUSH
    Write-TrackStep "4" "Sincronización con GitHub (git push)"
    $gitPushOutput = & git push origin main --quiet 2>&1
    Write-Utf8Log $gitPushOutput "Gray"
    
    Write-Utf8Log "============================================================" "Green"
    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] PROCESO FINALIZADO: Todo se actualizó y publicó con éxito." "Green"
    Write-Utf8Log "============================================================`n" "Green"
} else {
    Write-Utf8Log "============================================================" "Red"
    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR CRÍTICO: main.py falló (Código de salida $LASTEXITCODE)." "Red"
    Write-Utf8Log "[INFO] Proceso de Git abortado para proteger la consistencia del repositorio." "Yellow"
    Write-Utf8Log "============================================================`n" "Red"
}
