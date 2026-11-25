$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$configPath = Join-Path $PSScriptRoot 'configs\vascx.local.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    throw 'Missing configs/vascx.local.json. See docs/P2_D_SPEC.md.'
}
$env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
& $pythonPath -m rop_insight --config $configPath
exit $LASTEXITCODE
