# Run from the project folder:  .\run_eval.ps1
$key = Read-Host "Paste your Gemini API key (it stays only on your computer)"
$env:GEMINI_API_KEY = $key
python tools/eval_disease.py eval-images --limit 120 | Tee-Object -FilePath eval-results.txt
Write-Host "`nSaved to eval-results.txt"
