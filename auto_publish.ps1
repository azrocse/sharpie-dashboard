$repo = "C:\Users\Administrator\Desktop\sharpie-dashboard"
$log  = "$repo\refresh_log.txt"

$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 > $null

Set-Location $repo

"[$(Get-Date)] Iniciando refresco..." | Out-File $log -Append

python -B src\main.py *>> $log

if ($LASTEXITCODE -eq 0) {
    git add .
    git commit -m "Auto-refresh dashboard $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    git push origin main 2>&1 | Out-File $log -Append
    "[$(Get-Date)] Publicado." | Out-File $log -Append
} else {
    "[$(Get-Date)] ERROR: main.py fallo, no se publica HTML desactualizado." | Out-File $log -Append
}