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

Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Iniciando refresco..."

# 2. Ejecutar Python capturando su salida directamente en una variable
$pythonOutput = & python -B src\main.py 2>&1
Write-Utf8Log $pythonOutput

if ($LASTEXITCODE -eq 0) {
    # 3. Rastrea TODOS los archivos modificados, agregados o eliminados
    $gitAddOutput = & git add -A 2>&1
    Write-Utf8Log $gitAddOutput
    
    # Commit descriptivo indicando actualización completa del proyecto
    $commitMsg = "Auto-update: Datos, scripts y assets ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
    $gitCommitOutput = & git commit -m $commitMsg 2>&1
    Write-Utf8Log $gitCommitOutput
    
    # Publicar cambios a GitHub
    $gitPushOutput = & git push origin main --quiet 2>&1
    Write-Utf8Log $gitPushOutput
    
    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Proyecto actualizado y publicado con éxito."
} else {
    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR: main.py falló (Code $LASTEXITCODE), abortando commit."
}
