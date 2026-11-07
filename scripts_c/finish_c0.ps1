# Run from any directory: powershell -NoProfile -ExecutionPolicy Bypass -File <repo>/scripts_c/finish_c0.ps1
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv/Scripts/python.exe'
$taskDenseRoot = Join-Path $env:USERPROFILE '.cache/pegh/artifacts/c0-v1'

function Run-Python([string[]] $taskArguments) {
    & $taskPython @taskArguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed ($LASTEXITCODE): $($taskArguments -join ' ')" }
}

if (-not (Test-Path -LiteralPath $taskPython)) {
    uv sync --locked --python 3.12 --extra dev
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the locked Python environment' }
}

$taskMissingRaw = $false
foreach ($domain in @('programmers', 'unix')) {
    foreach ($name in @('corpus.jsonl', 'queries.jsonl', 'qrels.tsv')) {
        if (-not (Test-Path -LiteralPath "data/raw/$domain/$name")) { $taskMissingRaw = $true }
    }
}
if ($taskMissingRaw) { Run-Python @('scripts_a/fetch_inputs.py') }
Run-Python @('scripts_a/prepare_data.py')

foreach ($domain in @('programmers', 'unix')) {
    if (-not (Test-Path -LiteralPath "artifacts/sparse/$domain/index.sqlite3") -or
        -not (Test-Path -LiteralPath "artifacts/sparse/$domain/manifest.json")) {
        Run-Python @(
            'scripts_a/build_sparse.py', '--corpus', "data/raw/$domain/corpus.jsonl",
            '--domain', $domain, '--output', "artifacts/sparse/$domain"
        )
    }
}

foreach ($domain in @('programmers', 'unix')) {
    $taskExpected = if ($domain -eq 'programmers') { 32176 } else { 47382 }
    $taskIndex = Join-Path $taskDenseRoot $domain
    $taskManifest = Join-Path $taskIndex 'manifest.json'
    $taskLock = Join-Path $taskIndex '.build.lock'
    while ($true) {
        if (Test-Path -LiteralPath $taskManifest) {
            $taskState = Get-Content -LiteralPath $taskManifest -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($taskState.status -eq 'complete') { break }
            Write-Host "$domain dense checkpoint: $($taskState.ntotal)/$taskExpected"
        }
        $taskActive = $false
        if (Test-Path -LiteralPath $taskLock) {
            $taskPid = (Get-Content -LiteralPath $taskLock -Raw -Encoding UTF8 | ConvertFrom-Json).pid
            $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $taskPid"
            $taskActive = $null -ne $taskProcess -and $taskProcess.Name -eq 'python.exe' -and
                $taskProcess.CommandLine -like '*build_dense.py*'
        }
        if ($taskActive) {
            Write-Host "Waiting for active $domain dense build (PID $taskPid)..."
            Start-Sleep -Seconds 30
            continue
        }
        $taskArgs = @(
            'scripts_b/build_dense.py', '--corpus', "data/raw/$domain/corpus.jsonl",
            '--domain', $domain, '--expected-count', "$taskExpected", '--output', $taskIndex,
            '--cache-folder', 'artifacts/models', '--runtime', 'configs/runtime/cpu4.yaml'
        )
        if (Test-Path -LiteralPath $taskManifest) { $taskArgs += '--resume' }
        if (Test-Path -LiteralPath $taskLock) { $taskArgs += '--recover-stale-lock' }
        Run-Python $taskArgs
    }
    $taskVerification = Join-Path $taskDenseRoot "$domain-verification.json"
    if (-not (Test-Path -LiteralPath $taskVerification)) {
        Run-Python @(
            'scripts_b/verify_dense_index.py', '--index', $taskIndex,
            '--expected-count', "$taskExpected", '--output', $taskVerification
        )
    }
    $taskVerified = Get-Content -LiteralPath $taskVerification -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskCompleteIndex = Get-Content -LiteralPath $taskManifest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($taskVerified.status -ne 'passed' -or $taskVerified.document_count -ne $taskExpected -or
        $taskVerified.index_sha256 -ne $taskCompleteIndex.index_sha256 -or
        $taskVerified.manifest_sha256 -ne (Get-FileHash -LiteralPath $taskManifest -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw "$domain dense verification receipt differs from the current index"
    }

    $taskDenseRun = "results/quality/dense/$domain.jsonl"
    $taskSidecar = "$taskDenseRun.meta.json"
    if ((Test-Path -LiteralPath $taskDenseRun) -xor (Test-Path -LiteralPath $taskSidecar)) {
        throw "$domain dense ranking and sidecar must both exist or both be absent"
    }
    if (-not (Test-Path -LiteralPath $taskDenseRun)) {
        Run-Python @(
            'scripts_b/generate_dense_runs.py', '--index', $taskIndex,
            '--queries', "data/raw/$domain/queries.jsonl", '--output', $taskDenseRun,
            '--split', 'development_validation', '--cache-folder', 'artifacts/models',
            '--runtime', 'configs/runtime/cpu4.yaml'
        )
    }
}

$taskAudit = Get-Content -LiteralPath 'docs/person_a/validation/REAL_DATA_AUDIT.json' -Raw -Encoding UTF8 | ConvertFrom-Json
$taskDenseAudit = Get-Content -LiteralPath 'docs/person_a/validation/DENSE_REBUILD_AUDIT.json' -Raw -Encoding UTF8 | ConvertFrom-Json
$taskReceipt = [ordered]@{ status = 'passed'; created_at_utc = (Get-Date).ToUniversalTime().ToString('o'); domains = [ordered]@{} }

foreach ($domain in @('programmers', 'unix')) {
    $taskDataset = Get-Content -LiteralPath "data/manifests/$domain.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskIndex = Get-Content -LiteralPath (Join-Path $taskDenseRoot "$domain/manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $taskSparse = Get-Content -LiteralPath "artifacts/sparse/$domain/manifest.json" -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($kind in @('corpus', 'queries', 'qrels')) {
        $taskRawName = if ($kind -eq 'qrels') { 'qrels.tsv' } else { "$kind.jsonl" }
        $taskRawHash = (Get-FileHash -LiteralPath "data/raw/$domain/$taskRawName" -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($taskRawHash -ne $taskDataset.files.$kind.sha256) { throw "$domain $kind input checksum differs" }
    }
    if ($taskIndex.corpus_sha256 -ne $taskDataset.files.corpus.sha256) {
        throw "$domain dense index uses a different corpus"
    }
    if ($taskSparse.status -ne 'complete' -or $taskSparse.corpus_sha256 -ne $taskDataset.files.corpus.sha256 -or
        $taskSparse.document_count -ne $taskDataset.counts.documents -or
        $taskSparse.database_sha256 -ne (Get-FileHash -LiteralPath "artifacts/sparse/$domain/index.sqlite3" -Algorithm SHA256).Hash.ToLowerInvariant()) {
        throw "$domain sparse index differs from the audited corpus"
    }
    $taskMethods = [ordered]@{}
    foreach ($method in @('bm25', 'dense')) {
        $taskRun = "results/quality/$method/$domain.jsonl"
        $taskSidecar = "$taskRun.meta.json"
        if (-not (Test-Path -LiteralPath $taskRun) -or -not (Test-Path -LiteralPath $taskSidecar)) {
            throw "Missing $method/$domain ranking or sidecar"
        }
        $taskMeta = Get-Content -LiteralPath $taskSidecar -Raw -Encoding UTF8 | ConvertFrom-Json
        $taskHash = (Get-FileHash -LiteralPath $taskRun -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($taskHash -ne $taskMeta.ranking_sha256) { throw "$method/$domain ranking checksum differs" }
        if ($taskMeta.corpus_sha256 -ne $taskDataset.files.corpus.sha256 -or
            $taskMeta.queries_sha256 -ne $taskDataset.files.queries.sha256 -or
            $taskMeta.query_count -ne $taskDataset.counts.queries -or
            $taskMeta.split -ne 'development_validation' -or $taskMeta.output_k -ne 100) {
            throw "$method/$domain ranking metadata differs from the audited inputs"
        }
        if ($method -eq 'bm25' -and $taskMeta.retriever_hash -ne $taskSparse.retriever_hash) {
            throw "$domain BM25 ranking uses a different index"
        }
        if ($method -eq 'dense' -and $taskMeta.model_revision -ne $taskIndex.config.revision) {
            throw "$domain dense ranking uses a different model revision"
        }
        $taskOutput = "results/c0_audit/${method}_$domain"
        Run-Python @(
            'scripts_a/evaluate_quality.py', '--queries', "data/raw/$domain/queries.jsonl",
            '--qrels', "data/raw/$domain/qrels.tsv", '--run', $taskRun,
            '--domain', $domain, '--output', $taskOutput
        )
        $taskObserved = (Get-Content -LiteralPath "$taskOutput/summary.json" -Raw -Encoding UTF8 | ConvertFrom-Json).metrics
        $taskReference = if ($method -eq 'bm25') { $taskAudit.domains.$domain.metrics } else { $taskDenseAudit.domains.$domain.metrics }
        foreach ($metric in @('ndcg_at_10', 'mrr_at_10', 'recall_at_10', 'recall_at_100')) {
            if ([math]::Abs($taskObserved.$metric - $taskReference.$metric) -gt 0.000000000001) {
                throw "$method/$domain $metric differs from Part A's recorded result"
            }
        }
        $taskMethods[$method] = [ordered]@{ ranking_sha256 = $taskHash; metrics = $taskObserved }
    }
    $taskReceipt.domains[$domain] = [ordered]@{
        corpus_sha256 = $taskDataset.files.corpus.sha256
        dense_index_sha256 = $taskIndex.index_sha256
        methods = $taskMethods
    }
}

$taskReceiptPath = 'results/c0_audit/receipt.json'
$taskReceipt | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $taskReceiptPath -Encoding UTF8
Write-Host "C0 complete: $taskReceiptPath"
