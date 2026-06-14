$brainPath = "C:\Users\ezesu\.gemini\antigravity-ide\brain"
$outFile = "E:\PCW\VERA\acf_history.txt"
Write-Host "Buscando historial de ACF en $brainPath..."
Get-ChildItem -Path $brainPath -Recurse -Filter "transcript.jsonl" -ErrorAction SilentlyContinue | Select-String -Pattern "ACF" | Select-Object -Last 200 | Out-File $outFile -Encoding utf8
Write-Host "¡Listo! Historial extraído en $outFile"
