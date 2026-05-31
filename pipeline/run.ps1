$CLIPS_DIR  = "data\clips"
$OUTPUT     = "data\events.jsonl"
$LAYOUT     = "pipeline\config\store_layout.json"
$API_URL    = "http://localhost:8000"

Write-Host "=== Store Intelligence Pipeline ===" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path "data" | Out-Null

if (Test-Path $OUTPUT) {
    Remove-Item $OUTPUT
    Write-Host "Cleared previous events.jsonl"
}

# Running detection
Write-Host "Starting detection pipeline..." -ForegroundColor Yellow
python pipeline\detect.py `
    --clips  $CLIPS_DIR `
    --output $OUTPUT `
    --layout $LAYOUT `
    --api    $API_URL

Write-Host ""
Write-Host "=== Loading POS transactions ===" -ForegroundColor Cyan
python pipeline\pos_loader.py "data\Brigade_Bangalore_10_April_26.csv"

Write-Host ""
Write-Host "Pipeline complete!" -ForegroundColor Green
Write-Host "Events: $OUTPUT"