param(
    [ValidateSet("rule", "llm", "hybrid")]
    [string]$GeneratorMode = "rule",
    [int]$Port = 8512,
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$localPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$python = if ($PythonPath) { $PythonPath } elseif (Test-Path -LiteralPath $localPython) { $localPython } else { "python" }

$env:BANKINSIGHT_DATA_ENV = "real"
$env:BANKINSIGHT_GENERATOR_MODE = $GeneratorMode
$env:PYTHONPATH = "backend;."
Set-Location -LiteralPath $projectRoot

Write-Host "Candidate frontend: http://127.0.0.1:$Port/candidate"
Write-Host "Data environment: real; generator mode: $GeneratorMode"
& $python -m uvicorn --app-dir backend app.main:app --host 127.0.0.1 --port $Port
