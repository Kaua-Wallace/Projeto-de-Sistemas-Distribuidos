# Sobe o Processamento (:8002) e a Galeria (:8001). Ctrl+C encerra os dois.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

$proc = Start-Process -FilePath $py -ArgumentList "-m", "uvicorn", "processing_service.main:app", "--port", "8002" -NoNewWindow -PassThru

for ($i = 0; $i -lt 50; $i++) {
    try {
        Invoke-WebRequest -UseBasicParsing http://localhost:8002/health | Out-Null
        break
    } catch {
        Start-Sleep -Milliseconds 200
    }
}

$gal = Start-Process -FilePath $py -ArgumentList "-m", "uvicorn", "gallery_service.main:app", "--port", "8001" -NoNewWindow -PassThru

Write-Host "Processamento: http://localhost:8002 | Galeria: http://localhost:8001 (Ctrl+C para parar)"
try {
    Wait-Process -Id $proc.Id, $gal.Id
} finally {
    Stop-Process -Id $proc.Id, $gal.Id -ErrorAction SilentlyContinue
}
