# D5 — Combined schema drift

- **Change:** Removed `email`, renamed `amount_usd` → `order_total_usd`, changed IDs to `ORD-...`, and added `payment_method`.
- **Expected:** Clear schema warning or failure; no silent loss of required data.
- **Actual:** Pipeline **Success**, **0 warnings/errors**. Output was 300 × 8; `email` and `amount_usd` were NULL, `ORD-` IDs were preserved, and the new/renamed columns were omitted. Baseline comparison found **284 emails and 287 amounts lost**.
- **Chatbot:** It identified some missing fields, but mixed current data with ingestion/history information and reported several incorrect details.
- **Validation:** `d5.txt`: **0 FAIL, 4 DRIFT, 0 WARN**.

## AI repair check

AI Builder added a `schema_guard` before cleaning and claimed it would reject missing/unexpected source columns. Running the unchanged D5 input still completed with **0 warnings/errors** and produced output byte-identical to the unrepaired D5 result. The repair was therefore **not effective for this tested case**. No broader repair regression is claimed.

- **Files:** `datasets/Drift5_schema_combine.csv`, `datasets/RhombusAI_output_2st_Pipeline_Drift_5.csv`, `datasets/Drift6_schema_AIRepair.csv`, `observations/validation-output/d5.txt`, `repair.txt`.

## Evidence

**D5 logs**

![D5 logs](../evidence/d5-logs.png)

**D5 chatbot**

![D5 chatbot](../evidence/d5-chatbot.png)

**AI repair change**

![AI repair change](../evidence/repair-config.png)

**AI repair run**

![AI repair run](../evidence/repair-logs.png)
