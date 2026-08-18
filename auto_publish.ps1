# 0. Evitar bucle en ejecuciones automáticas
if ([Environment]::UserInteractive -and -not $env:PS_HIDDEN) {
    $env:PS_HIDDEN = "1"
    Start-Process powershell.exe -ArgumentList "-ExecutionPolicy Bypass -WindowStyle Hidden -Command `"`$env:PS_HIDDEN='1'; & '$PSCommandPath'`"" -WindowStyle Hidden
    exit
}

$repo = "C:\Users\Administrator\Desktop\sharpie-dashboard"
$log  = "$repo\refresh_log.txt"

# 1. Configuración de entorno
$env:PYTHONIOENCODING = "utf-8"
$OutputEncoding = [System.Text.Encoding]::UTF8

# Evitar error de consola no válida
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # Ignorar si no hay consola interactiva adjunta
}

Set-Location $repo

function Write-Utf8Log ($text) {
    $text | Out-File -FilePath $log -Append -Encoding utf8 -ErrorAction SilentlyContinue
}

Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Iniciando refresco..."

# 2. Ejecutar Python redirigiendo log
python -B src\main.py 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

if ($LASTEXITCODE -eq 0) {
    # 3. Publicación en Git
    git add -A 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    
    $commitMsg = "Auto-update: Datos, scripts y assets ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
    git commit -m $commitMsg 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    
    git push origin main --quiet 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    
    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Proyecto actualizado y publicado con éxito."
} else {
    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR: main.py falló (Code $LASTEXITCODE), abortando commit."
}