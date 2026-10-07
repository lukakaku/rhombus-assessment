# Run from the rhombus-assessment project root. Uses the final reviewed validator.
$ErrorActionPreference = 'Continue'
$root = (Get-Location).Path
$validator = Join-Path $root 'data-validation\validate_cleaning.py'
$dataset = Join-Path $root 'datasets'
$logs = Join-Path $root 'observations\validation-output'
$baseline = Join-Path $dataset 'RhombusAI_output_2st_Pipeline_Manual_1.csv'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
if (-not (Test-Path -LiteralPath $validator)) { throw "Validator missing: $validator" }
if (-not (Test-Path -LiteralPath $baseline)) { throw "Baseline output missing: $baseline" }

# The cases and filenames below are taken from your screenshot, except S2's output
# name, taken from the CSV shared earlier in this conversation.
$cases = @(
    @('baseline','base.csv',                       'RhombusAI_output_2st_Pipeline_Manual_1.csv'),
    @('d1',      'Drift1_schema_drop_column.csv',   'RhombusAI_output_2st_Pipeline_Drift_1.csv'),
    @('d2',      'Drift2_schema_rename_column.csv', 'RhombusAI_output_2st_Pipeline_Drift_2.csv'),
    @('d3',      'Drift3_schema_change_type.csv',   'RhombusAI_output_2st_Pipeline_Drift_3.csv'),
    @('d4',      'Drift4_schema_add_column.csv',    'RhombusAI_output_2st_Pipeline_Drift_4.csv'),
    @('d5',      'Drift5_schema_combine.csv',       'RhombusAI_output_2st_Pipeline_Drift_5.csv'),
    @('repair',  'Drift5_schema_combine.csv',       'Drift6_schema_AIRepair.csv'),
    @('s1',      'Semantic1_amount_cents.csv',      'RhombusAI_output_Semantic1.csv'),
    @('s2',      'Semantic2_date_ddmm.csv',         'RhombusAI_output_Semantic2.csv')
)

$summary = @()
foreach ($entry in $cases) {
    $case = $entry[0]; $inName = $entry[1]; $outName = $entry[2]
    $src = Join-Path $dataset $inName
    $out = Join-Path $dataset $outName
    $log = Join-Path $logs "$case.txt"
    Write-Host "`n========== $case ==========" -ForegroundColor Cyan
    $missing = @($src, $out) | Where-Object { -not (Test-Path -LiteralPath $_) }
    if ($missing.Count -gt 0) {
        # Overwrite an older report with a clear status; do not accidentally leave stale results.
        $msg = "NOT RUN: required file missing: $($missing -join '; ')"
        $msg | Set-Content -LiteralPath $log -Encoding UTF8
        Write-Warning $msg
        $summary += "${case}: NOT RUN (missing file)"
        continue
    }
    $params = @($src, $out, '--case', $case)
    if ($case -ne 'baseline') { $params += @('--baseline', $baseline) }
    # Tee-Object overwrites the old log.  A drift exit code of 1 is often EXPECTED.
    & "$PSScriptRoot\.venv\Scripts\python.exe" $validator @params 2>&1 | Tee-Object -FilePath $log
    $status = $LASTEXITCODE
    "EXIT CODE: $status" | Tee-Object -FilePath $log -Append
    $summary += "${case}: EXIT CODE $status"
}

# Repeatability is verified with the earlier manual and scheduled runs from
# the SAME original pipeline, instead of mixing runs from different pipelines.
$oldManual = Join-Path $dataset 'RhombusAI_output_After_Pipeline_Manual_Run_1.csv'
$oldScheduled = Join-Path $dataset 'RhombusAI_output_After_Pipeline_Schedule_Run_1.csv'
$repeatLog = Join-Path $logs 'baseline_repeat.txt'
if ((Test-Path -LiteralPath $oldManual) -and (Test-Path -LiteralPath $oldScheduled) -and
    (Test-Path -LiteralPath (Join-Path $dataset 'base.csv'))) {
    Write-Host "`n========== baseline_repeat (earlier pipeline) ==========" -ForegroundColor Cyan
    & "$PSScriptRoot\.venv\Scripts\python.exe" $validator (Join-Path $dataset 'base.csv') $oldManual --case baseline --repeat $oldScheduled 2>&1 | Tee-Object -FilePath $repeatLog
    $status = $LASTEXITCODE
    "EXIT CODE: $status" | Tee-Object -FilePath $repeatLog -Append
    $summary += "baseline_repeat: EXIT CODE $status"
} else {
    'NOT RUN: earlier manual/scheduled output(s) missing' | Set-Content -LiteralPath $repeatLog -Encoding UTF8
    $summary += 'baseline_repeat: NOT RUN (missing file)'
}
$summaryPath = Join-Path $logs 'summary.txt'
$summary | Set-Content -LiteralPath $summaryPath -Encoding UTF8
Write-Host "`nAll available tests finished. Results saved in: $logs" -ForegroundColor Green
$summary | ForEach-Object { Write-Host $_ }
