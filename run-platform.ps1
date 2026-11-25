$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$configPath = Join-Path $PSScriptRoot 'configs\p3b.local.json'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Create the GUI .venv first. See docs/RUNBOOK.md.' }
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Configure configs/p3b.local.json first. See docs/RUNBOOK.md.' }
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $pythonPath -m rop_insight --config $configPath
exit $LASTEXITCODE
