$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$configPath = Join-Path $PSScriptRoot 'configs\p3.local.json'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Missing configs/p3.local.json. See docs/P3_A.md.' }
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $pythonPath -m rop_insight --config $configPath
exit $LASTEXITCODE
