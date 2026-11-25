$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$configPath = Join-Path $PSScriptRoot 'configs\a6.local.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    throw 'Missing configs/a6.local.json. See docs/P2_E_A6.md.'
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $pythonPath -m rop_insight --config $configPath
exit $LASTEXITCODE
