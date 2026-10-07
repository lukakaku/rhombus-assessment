# Rhombus AI — ETL QA take-home

## Setup

This assessment builds a cloud ETL pipeline, injects schema and semantic drift, and checks pipeline behavior, logs, chatbot diagnosis, repair, and output correctness.

- **Source:** GCS (`rhombus-gcs-luka-input-001`). AWS S3 was attempted first but returned AccessDenied; Rhombus support approved GCS as the substitute source.
- **Destination:** GCS (`rhombus-gcs-luka-001`).
- **Pipeline:** Data Input → AI Builder cleaning → Remove Duplicates (`order_id`, keep first) → GCS output.
- **Baseline input:** 320 rows, 8 columns, including 20 duplicate order IDs and intentionally messy values.
- **Expected clean output:** 300 rows, original 8 columns.

Baseline validation passed with **0 FAIL / 0 WARN** on the final pipeline. Two earlier baseline outputs also matched each other byte-for-byte, showing repeatability for those two observed runs.

## Run data validation

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Set-ExecutionPolicy -Scope Process Bypass   # only if needed
.\run_validation.ps1
```

Validation logs are written to `observations/validation-output/`. `DRIFT` and exit code 1 are expected when an injected change is detected; `FAIL` is reported separately for rule/design mismatches.

## Results

| Case                                          | Pipeline / logs     | Main result                               | Independent validation        |
| --------------------------------------------- | ------------------- | ----------------------------------------- | ----------------------------- |
| Baseline                                      | Success             | 320 → 300; expected cleaning              | 0 FAIL, 0 WARN                |
| [D1 Drop](observations/d1-drop-email.md)      | Success; no warning | `email` recreated as NULL                 | 284 emails lost               |
| [D2 Rename](observations/d2-rename-amount.md) | Success; no warning | renamed amount omitted; `amount_usd` NULL | 287 amounts lost              |
| [D3 Type](observations/d3-id-type.md)         | Success; no warning | `ORD-` IDs preserved                      | other fields unchanged        |
| [D4 Add](observations/d4-add-column.md)       | Success; no warning | `payment_method` omitted                  | output identical to baseline  |
| [D5 Combined](observations/d5-combined.md)    | Success; no warning | multiple changes passed silently          | 284 emails / 287 amounts lost |
| [S1 Cents](observations/s1-amount-cents.md)   | Success; no warning | amounts became exactly 100× baseline      | 287 amounts changed           |
| [S2 Date](observations/s2-date-ddmm.md)       | Success; no warning | 120 dates silently changed                | 2 rule FAIL; 2 drift findings |

## Main findings

1. **Schema drift passed silently.** In D1, D2 and D5 the run reported success with no warning while an entire business column became NULL (284 emails, 287 amounts). The synced dataset preview had kept the removed fields as `Unsupported` / null columns, which may be related (not established).
2. **Semantic drift is invisible to the cleaning rules, and the date parser did not honour the strict rule.** S1 multiplied valid amounts by exactly 100 and nothing flagged it. In S2 the rule says "parse strictly as MM/DD/YYYY, do not guess", yet 167 DD/MM dates with day > 12 were accepted as real dates instead of becoming NULL, and 120 ambiguous dates were silently swapped. The preview already showed the wrong dates before the cleaning step ran, so the interpretation seems to happen at ingestion (cause not established).
3. **The AI Builder's diagnosis depends on how it is asked, and its repair did not work.** It explained D1 when told what changed, missed the D2 loss when not told, found S1 only with an explicit baseline-comparison prompt, and missed S2. The `schema_guard` it built for D5 did not change the outcome.

Integration and scheduling limitations are summarized in [known issues](observations/known-issues.md).

 

## How to reproduce a drift case

1. In the input bucket, overwrite `base.csv` with the drifted file.
2. In Rhombus: Data Input → Third Party Sources → Sync Now. Open the dataset preview and confirm the values changed.
3. Select the dataset, then Run manually, because scheduled runs were not reliable, (see known issues).
4. Download the new output from the destination bucket and run
   data validation.
5. Ask the chatbot: *informed* = tell it what changed; *blind* = "review the latest run for anomalies" without hints. The prompt used is stated in each observation file.

## Usability feedback

**What was most helpful.** The AI Builder turned a detailed, rule-by-rule prompt into a working cleaning pipeline in minutes, and it's easy to see each step. When a node did fail, the message listed the expected and the actual columns. The chatbot was also genuinely useful when asked a specific question, such as comparing the latest output with the baseline, where it found the exact 100× amount shift.

**What was frustrating, and how it could be better.** The problem is that changes in the source data were invisible: runs finished as successful while a whole column came back empty. The S3 connection error pointed at the folder and policy, while CloudTrail showed the denial on the very first call, so I spent a long time on the wrong cause. Scheduling was hard to trust: `Next run` went blank, the execution history stayed empty, and no run appeared without an edit on the canvas. In the source picker, datasets are shown as `placeholder_file` , so I had to open each preview to identify my file; naming datasets after their file clearly would help. 

## Run UI and API tests

UI tests use Playwright against an already authenticated Chrome session. Start a separate Chrome profile with local remote debugging enabled, log in to Rhombus normally, and keep that Chrome window open:

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --remote-debugging-address=127.0.0.1 `
  --user-data-dir="$PWD\.auth\chrome-test-profile" `
  "https://rhombusai.com/"
```

Run the UI tests from the project root:

```powershell
.\.venv\Scripts\python.exe -m pytest ui-tests -v -s
```

The UI tests are read-only. `UI-01` checks the existing drift pipeline configuration; `UI-02` checks the saved baseline schedule and confirms that it is currently inactive.

Authenticated API test:

```powershell
$env:RHOMBUS_TOKEN="<token>"
$env:RHOMBUS_ORG_ID="<org-id>"
.\.venv\Scripts\python.exe -m pytest api-tests -v -s

Remove-Item Env:RHOMBUS_TOKEN
Remove-Item Env:RHOMBUS_ORG_ID
```

## UI / API test results

| Test   | Check                                                                                                                  | Result |
| ------ | ---------------------------------------------------------------------------------------------------------------------- | ------ |
| UI-01  | Existing drift pipeline: GCS input, AI Builder / Transform, GCS output, Schedule UI                                    | PASS   |
| UI-02  | Existing baseline schedule: saved schedule visible, `Custom: */5 * * * *`, activation switch off                       | PASS   |
| API-01 | Authenticated `GET /api/dataset/analyzer/v2/projects/5289/nodes`: 200, JSON node structure, input/output nodes present | PASS   |
| API-02 | Same endpoint without authentication is rejected                                                                       | PASS   |
| API-03 | Same endpoint with an invalid Bearer token is rejected                                                                 | PASS   |

## Repository contents

- `datasets/` — baseline and drift inputs/outputs
- `data-validation/` — validation script
- `observations/` — one Markdown file per drift case, validation logs, and known issues
- `evidence/` — selected screenshots
- `ui-tests/` — Playwright read-only UI automation for pipeline configuration and schedule checks
- `api-tests/` — direct backend API tests for authenticated, unauthenticated, and invalid-token requests
- Demo video: https://www.loom.com/share/f89580e6b85f490389d0da743391528d
