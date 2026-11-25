$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$configPath = Join-Path $PSScriptRoot 'configs\p3b.local.json'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Missing configs/p3b.local.json. See docs/P3_B.md.' }
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $pythonPath -m rop_insight --config $configPath
exit $LASTEXITCODE
