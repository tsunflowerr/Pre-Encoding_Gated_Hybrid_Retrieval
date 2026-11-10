param([switch]$AllowSample)

$ErrorActionPreference = 'Stop'
$python = Join-Path $PWD '.venv/Scripts/python.exe'
$ruff = Join-Path $PWD '.venv/Scripts/ruff.exe'

& uv sync --locked --python 3.12 --extra dev
if ($LASTEXITCODE -ne 0) { throw 'Locked environment sync failed.' }
& $python -X utf8 -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Full test suite failed.' }
& $python -X utf8 -m pytest -q tests/c
if ($LASTEXITCODE -ne 0) { throw 'Part C test suite failed.' }
& $ruff check .
if ($LASTEXITCODE -ne 0) { throw 'Ruff check failed.' }
& $python -X utf8 scripts_c/report_gating.py
if ($LASTEXITCODE -ne 0) { throw 'C7 report regeneration failed.' }

$report = Get-Content -LiteralPath 'results/reports/c7_report.json' -Raw -Encoding UTF8 |
    ConvertFrom-Json
if (-not $AllowSample -and $report.online_status -ne 'complete') {
    throw 'Full 10-fold, five-repeat online benchmark is required for final release.'
}
Write-Host "C7 report hash: $($report.report_hash)"
Write-Host "Online status: $($report.online_status)"
