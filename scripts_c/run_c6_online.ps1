param(
    [int]$Repetitions = 5,
    [string]$OutputRoot = 'results/benchmark/c6_full',
    [string]$Runtime = 'configs/runtime/cpu4.yaml',
    [switch]$DetailedStages,
    [ValidateSet('programmers', 'unix')][string]$OnlyDomain,
    [ValidateRange(0, 4)][Nullable[int]]$OnlyFold = $null,
    [switch]$RestartIncomplete
)

$ErrorActionPreference = 'Stop'
$python = Join-Path $PWD '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'The locked .venv is missing.' }
if (-not (Test-Path -LiteralPath 'results/frozen/c6_manifest.json')) { throw 'C6 freeze manifest is missing.' }
& $python -X utf8 -c "import json; from pegh.profiling.provenance import source_snapshot; x=json.load(open('results/frozen/c6_manifest.json',encoding='utf-8')); assert source_snapshot()['combined_sha256']==x['source_snapshot_hash'], 'Source/config changed after C6 freeze'"
if ($LASTEXITCODE -ne 0) { throw 'Source/config differs from C6 freeze.' }

$domains = if ($OnlyDomain) { @($OnlyDomain) } else { @('programmers', 'unix') }
$folds = if ($null -ne $OnlyFold) { @($OnlyFold) } else { @(0, 1, 2, 3, 4) }
foreach ($domain in $domains) {
    foreach ($fold in $folds) {
        $name = "${domain}_fold_${fold}"
        $registry = "results/frozen/benchmark/$name.json"
        $queries = "results/frozen/benchmark_inputs/${name}_test.jsonl"
        $warmup = "results/frozen/benchmark_inputs/${name}_warmup.jsonl"
        $output = Join-Path $OutputRoot $name
        foreach ($required in @($registry, $queries, $warmup)) {
            if (-not (Test-Path -LiteralPath $required)) { throw "Missing $required" }
        }
        if (Test-Path -LiteralPath $output) {
            $manifest = Join-Path $output 'manifest.json'
            $state = if (Test-Path -LiteralPath $manifest) {
                Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
            } else { $null }
            if ($state -and $state.status -eq 'complete' -and
                $state.settings.repetitions -eq $Repetitions -and
                $state.domain -eq $domain -and $state.fold -eq $fold) {
                if (-not (Test-Path -LiteralPath (Join-Path $output 'summary.json'))) {
                    & $python -X utf8 scripts_b/report_efficiency.py --run $output
                    if ($LASTEXITCODE -ne 0) { throw "Efficiency report failed: $name" }
                }
                Write-Host "Already complete: $name"
                continue
            }
            if (-not $RestartIncomplete) {
                throw "Incomplete or mismatched run: $output. Inspect it, then use -RestartIncomplete to archive and rerun it."
            }
            $archive = "${output}.interrupted.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
            if (Test-Path -LiteralPath $archive) { throw "Archive already exists: $archive" }
            $rootPath = [IO.Path]::GetFullPath($OutputRoot).TrimEnd([IO.Path]::DirectorySeparatorChar)
            $runPath = [IO.Path]::GetFullPath($output)
            $archivePath = [IO.Path]::GetFullPath($archive)
            $rootPrefix = $rootPath + [IO.Path]::DirectorySeparatorChar
            if (-not $runPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase) -or
                -not $archivePath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Run and archive must stay inside $rootPath"
            }
            Move-Item -LiteralPath $output -Destination $archive
            Write-Host "Archived interrupted run: $archive"
        }
        $stageArgs = if ($DetailedStages) { @('--detailed-stages') } else { @() }
        & $python -X utf8 scripts_b/benchmark_online.py `
            --registry $registry --queries $queries --warmup-queries $warmup `
            --domain $domain --split test --fold $fold --output $output `
            --repetitions $Repetitions --runtime $Runtime @stageArgs
        if ($LASTEXITCODE -ne 0) { throw "Benchmark failed: $name" }
        & $python -X utf8 scripts_b/report_efficiency.py --run $output
        if ($LASTEXITCODE -ne 0) { throw "Efficiency report failed: $name" }
    }
}
