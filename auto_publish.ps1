$repo = "C:\Users\Administrator\Desktop\sharpie-dashboard"
$log  = "$repo\refresh_log.txt"

# 1. Configuración de entorno y consola a UTF-8
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

Set-Location $repo

function Write-Utf8Log ($text) {
    $text | Out-File -FilePath $log -Append -Encoding utf8
}

Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Iniciando refresco..."

# 2. Ejecutar Python
python -B src\main.py 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

if ($LASTEXITCODE -eq 0) {
    # 3. Rastrea TODOS los archivos modificados, agregados o eliminados
    git add -A 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    
    # Commit descriptivo indicando actualización completa del proyecto
    $commitMsg = "Auto-update: Datos, scripts y assets ($(Get-Date -Format 'yyyy-MM-dd HH:mm'))"
    git commit -m $commitMsg 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    
    # Publicar cambios a GitHub
    git push origin main --quiet 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    
    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Proyecto actualizado y publicado con éxito."
} else {
    Write-Utf8Log "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] ERROR: main.py falló (Code $LASTEXITCODE), abortando commit."
}