$repo = "C:\Users\Administrator\Desktop\sharpie-dashboard"
$log  = "$repo\refresh_log.txt"

Set-Location $repo

"[$(Get-Date)] Iniciando refresco..." | Out-File $log -Append

python -B src\main.py *>> $log

git add .
git commit -m "Auto-refresh dashboard $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git push origin main *>> $log

"[$(Get-Date)] Publicado." | Out-File $log -Append