param(
    [switch]$PrepareEvidence,
    [ValidateSet('thesis', 'main')][string]$EntryPoint = 'thesis'
)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if ($PrepareEvidence) {
        & '..\.venv\Scripts\python.exe' 'tools\prepare_evidence.py'
        if ($LASTEXITCODE -ne 0) { throw 'Cannot prepare report evidence.' }
    }
    New-Item -ItemType Directory -Path 'build' -Force | Out-Null
    $texInput = "$EntryPoint.tex"
    $bibJob = "build/$EntryPoint"
    & xelatex --disable-installer -interaction=nonstopmode -halt-on-error -output-directory=build $texInput
    if ($LASTEXITCODE -ne 0) { throw "First XeLaTeX pass failed. See build/$EntryPoint.log." }
    & bibtex $bibJob
    if ($LASTEXITCODE -ne 0) { throw "BibTeX failed. See build/$EntryPoint.blg." }
    for ($pass = 0; $pass -lt 2; $pass++) {
        & xelatex --disable-installer -interaction=nonstopmode -halt-on-error -output-directory=build $texInput
        if ($LASTEXITCODE -ne 0) { throw "XeLaTeX failed. See build/$EntryPoint.log." }
    }
    Copy-Item -LiteralPath "build\$EntryPoint.pdf" -Destination 'PE_GH_REPORT.pdf' -Force
} finally {
    Pop-Location
}
