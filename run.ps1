$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Please create .venv and install requirements first. See README.md.'
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $pythonPath -m rop_insight
exit $LASTEXITCODE
