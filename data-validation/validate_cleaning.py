"""Rhombus take-home: independent data validation (fixed version).

Checks output schema, cleaning rules, first-occurrence deduplication, schema drift,
regression against a known-good output, semantic drift and repeatability.

Usage:
    python validate_cleaning.py INPUT.csv OUTPUT.csv --case baseline
    python validate_cleaning.py INPUT.csv OUTPUT.csv --case d5 --baseline BASELINE_OUTPUT.csv
    python validate_cleaning.py INPUT.csv OUTPUT.csv --case s2 --baseline BASELINE_OUTPUT.csv
    python validate_cleaning.py INPUT.csv OUTPUT.csv --case baseline --repeat SECOND_OUTPUT.csv

Cases: baseline, d1 (drop email), d2 (rename amount), d3 (type change ID),
       d4 (add payment method), d5 (combined), repair (d5 with AI repair),
       s1 (USD to cents), s2 (MM/DD to DD/MM).

Exit codes: 0 = valid and no drift found, 1 = drift/data mismatch detected,
            2 = invalid/missing files or unusable test data.
A nonzero result in an injected-drift case is often an EXPECTED test outcome.
"""
import argparse
import hashlib
import math
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

COLS = ["order_id", "customer_name", "email", "order_date",
        "amount_usd", "quantity", "status", "country"]
COUNTRY_MAP = {"united states": "US", "united kingdom": "UK", "australia": "AU",
               "new zealand": "NZ", "canada": "CA"}
CODES = {"US", "UK", "AU", "NZ", "CA"}
STATUSES = {"pending", "shipped", "delivered", "cancelled"}
NULLS = {"", "null", "none", "nan", "n/a"}
SCHEMAS = {
    "baseline": COLS, "d1": [c for c in COLS if c != "email"],
    "d2": ["order_total_usd" if c == "amount_usd" else c for c in COLS],
    "d3": COLS, "d4": COLS + ["payment_method"],
    "d5": ["order_id", "customer_name", "order_date", "order_total_usd",
           "quantity", "status", "country", "payment_method"],
    "s1": COLS, "s2": COLS,
}
SCHEMAS["repair"] = SCHEMAS["d5"]


def null(v):
    return str(v).strip().lower() in NULLS


def clean_text(v):
    return v.strip() or ""


def clean_email(v):
    v = v.strip().lower()
    if not v or " " in v or v.count("@") != 1:
        return ""
    local, domain = v.split("@")
    return v if local and "." in domain else ""


def clean_date(v, date_format):
    try:
        return datetime.strptime(v.strip(), date_format).strftime("%Y-%m-%d")
    except ValueError:
        return ""


def clean_amount(v):
    try:
        x = float(re.sub(r"[$,\s]", "", v))
        return str(x) if math.isfinite(x) and x >= 0 else ""
    except ValueError:
        return ""


def clean_quantity(v):
    v = v.strip()
    return str(int(v)) if re.fullmatch(r"\d+", v) and int(v) > 0 else ""


def clean_status(v):
    v = v.strip().lower()
    return v if v in STATUSES else ""


def clean_country(v):
    v = v.strip()
    return v.upper() if v.upper() in CODES else COUNTRY_MAP.get(v.lower(), "")


def same(col, a, b):
    if null(a) or null(b):
        return null(a) and null(b)
    if col in ("amount_usd", "quantity"):
        try:
            return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) < 0.005
        except ValueError:
            return False
    return str(a) == str(b)


def read_csv(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")


def reference(source, case):
    # Absent source columns are *not* silently treated as normal: they are
    # recorded as schema drift separately. This models observed fixed-output behavior.
    df = source.copy()
    for col in COLS:
        if col not in df.columns:
            df[col] = ""
    fmt = "%m/%d/%Y"  # the documented rule; semantic drift is judged in [3] against the baseline
    result = pd.DataFrame({
        "order_id": df["order_id"].str.strip(),
        "customer_name": df["customer_name"].map(clean_text),
        "email": df["email"].map(clean_email),
        "order_date": df["order_date"].map(lambda v: clean_date(v, fmt)),
        "amount_usd": df["amount_usd"].map(clean_amount),
        "quantity": df["quantity"].map(clean_quantity),
        "status": df["status"].map(clean_status),
        "country": df["country"].map(clean_country),
    })
    return result.drop_duplicates(keep="first").drop_duplicates(
        subset="order_id", keep="first").reset_index(drop=True)


def canonical_id(value, case):
    value = str(value).strip()
    # D3 and D5 deliberately change 1001 -> ORD-1001. Not generic inference.
    return value.removeprefix("ORD-") if case in ("d3", "d5", "repair") else value


def hash_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(args):
    failures = 0
    changes = 0
    warnings = 0

    def check(ok, text):
        nonlocal failures
        print(("PASS  " if ok else "FAIL  ") + text)
        if not ok:
            failures += 1

    def drift(text):
        nonlocal changes
        print("DRIFT " + text)
        changes += 1

    def warn(text):
        nonlocal warnings
        print("WARN  " + text)
        warnings += 1

    src, out = read_csv(args.input), read_csv(args.output)
    if "order_id" not in src.columns or "order_id" not in out.columns:
        print("ERROR order_id missing: cannot safely align records")
        return 2

    print(f"CASE {args.case} | source={len(src)} rows | output={len(out)} rows")
    print("\n[1] INPUT SCHEMA / DRIFT")
    expected_cols = SCHEMAS[args.case]
    check(list(src.columns) == expected_cols,
          f"source matches declared {args.case} test design")
    missing = [c for c in COLS if c not in src.columns]
    extra = [c for c in src.columns if c not in COLS]
    if missing or extra:
        drift(f"source schema: missing={missing}; extra={extra}")

    if args.case in ("d3", "d5", "repair"):
        id_type_changed = all(re.fullmatch(r"ORD-\d+", x.strip()) for x in src["order_id"])
        check(id_type_changed, "order_id values converted to ORD-<digits> text")
        if id_type_changed:
            drift("order_id value format: numeric IDs -> ORD-prefixed text (CSV type inferred)")

    print("\n[2] CLEANING, OUTPUT STRUCTURE, DEDUPLICATION")
    exp = reference(src, args.case)
    check(list(out.columns) == COLS, "output has exactly 8 columns in baseline order")
    check(len(out) == len(exp), f"row count {len(out)} (expected {len(exp)})")
    check(not out.duplicated().any(), "no exact duplicate output rows")
    check(not out["order_id"].duplicated().any(), "no duplicate output order_id")
    ids_match = out["order_id"].tolist() == exp["order_id"].tolist()
    check(ids_match, "first-occurrence input row order and IDs preserved")
    if "order_id" in out and "order_id" in exp:
        eids = exp["order_id"].tolist()
        gids = out["order_id"].tolist()
        if len(eids) == len(set(eids)) and len(gids) == len(set(gids)):
            em = exp.set_index("order_id"); gm = out.set_index("order_id")
            common = [oid for oid in eids if oid in gm.index]
            for col in COLS[1:]:
                if col not in out.columns:
                    continue
                bad = [oid for oid in common if not same(col, em.at[oid, col], gm.at[oid, col])]
                check(not bad, f"{col}: {len(bad)} cleaning-rule differences"
                      + (f" (examples: {bad[:3]})" if bad else ""))
        else:
            print("SKIP  field comparison requires unique order_id values")

    # Formatting warnings should not change the meaning of a correct result.
    for col in out.columns:
        literals = out[col].astype(str).str.strip().str.lower()
        n = int(literals.isin(NULLS - {""}).sum())
        if n:
            warn(f"{col}: {n} NULL values written as text rather than empty cells")
    if "quantity" in out:
        n = int(out["quantity"].str.fullmatch(r"\d+\.\d+").sum())
        if n:
            warn(f"quantity contains decimal-form integers in {n} rows")

    print("\n[3] BASELINE COMPARISON / SEMANTIC DRIFT")
    if args.baseline:
        base = read_csv(args.baseline)
        if "order_id" not in base.columns:
            print("ERROR baseline lacks order_id")
            return 2
        b = base.copy(); g = out.copy()
        b["_key"] = b["order_id"].map(lambda x: canonical_id(x, "baseline"))
        g["_key"] = g["order_id"].map(lambda x: canonical_id(x, args.case))
        if b["_key"].duplicated().any() or g["_key"].duplicated().any():
            print("ERROR ambiguous IDs after baseline alignment")
            return 2
        bm, gm = b.set_index("_key"), g.set_index("_key")
        keys = [key for key in bm.index if key in gm.index]
        check(len(keys) == len(bm) == len(gm),
              f"baseline records aligned: {len(keys)} / {len(bm)}")
        changed_cols, to_null_cols = {}, {}
        for col in COLS[1:]:
            if col not in bm.columns or col not in gm.columns:
                continue
            changed = [key for key in keys if not same(col, bm.at[key, col], gm.at[key, col])]
            changed_cols[col] = changed
            to_null = [k for k in changed if null(gm.at[k, col]) and not null(bm.at[k, col])]
            from_null = [k for k in changed if null(bm.at[k, col]) and not null(gm.at[k, col])]
            to_null_cols[col] = to_null
            other = len(changed) - len(to_null) - len(from_null)
            if changed:
                drift(f"baseline comparison: {col} changed for {len(changed)} orders "
                      f"({len(to_null)} became NULL, {other} changed value, {len(from_null)} filled from NULL)"
                      f" (examples: {changed[:3]})")
            else:
                print(f"PASS  baseline comparison: {col} unchanged")
        if args.case == "s1":
            numeric = [(float(bm.at[k, "amount_usd"]), float(gm.at[k, "amount_usd"]))
                       for k in keys if not null(bm.at[k, "amount_usd"])
                       and not null(gm.at[k, "amount_usd"])]
            positive = [(a, v) for a, v in numeric if a > 0]
            exact100 = bool(positive) and all(math.isclose(v, 100*a, abs_tol=0.005)
                                               for a, v in positive)
            print(f"SEMANTIC amount scale: {len(positive)} comparable positive values; "
                  f"exact 100x = {exact100}")
        if args.case == "s2":
            def swap(d):
                y, m, dd = d.split("-")
                return f"{y}-{dd}-{m}"
            ch = changed_cols.get("order_date", [])
            wrong = [k for k in ch if not null(gm.at[k, "order_date"]) and not null(bm.at[k, "order_date"])]
            swapped = [k for k in wrong if gm.at[k, "order_date"] == swap(bm.at[k, "order_date"])]
            print(f"SEMANTIC dates changed vs original meaning: {len(ch)} "
                  f"({len(wrong)} silently different dates, {len(swapped)} of them exact day/month swaps; "
                  f"{len(to_null_cols.get('order_date', []))} became NULL)")
        if (len(keys) == len(bm) == len(gm) and list(out.columns) == list(base.columns)
                and not any(changed_cols.values())):
            same_bytes = hash_file(args.output) == hash_file(args.baseline)
            print("INFO  output values identical to the baseline output"
                  + (" (byte-identical, same SHA-256)" if same_bytes else " (different file bytes)"))
        if extra:
            print(f"INFO  new source columns omitted from contracted 8-column output: {extra}")
    else:
        print("SKIP  no --baseline supplied; cross-run drift/semantic changes not assessed")

    print("\n[4] DETERMINISM (IF TWO RUNS WERE PROVIDED)")
    if args.repeat:
        second = read_csv(args.repeat)
        exact = hash_file(args.output) == hash_file(args.repeat)
        values_same = list(out.columns) == list(second.columns) and out.equals(second)
        check(values_same, "two outputs have identical table values and row order")
        print("PASS  byte-identical SHA-256" if exact else
              "INFO  different SHA-256 (CSV formatting/serialization may differ)")
        if not exact and values_same:
            warn("same table, different file bytes")
    else:
        print("SKIP  provide --repeat SECOND_OUTPUT.csv to test repeatability")

    print(f"\nSUMMARY: {failures} rule/design FAIL, {changes} drift/change finding(s), "
          f"{warnings} WARN")
    return 1 if failures or changes else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", help="actual source CSV used by this pipeline run")
    parser.add_argument("output", help="actual GCS output CSV")
    parser.add_argument("--case", choices=SCHEMAS.keys(), required=True)
    parser.add_argument("--baseline", help="successful CLEAN baseline output CSV")
    parser.add_argument("--repeat", help="another output of the same exact input/pipeline")
    options = parser.parse_args()
    if options.case != "baseline" and not options.baseline:
        parser.error("--baseline is required for every case except 'baseline' "
                     "(without it, drift that the cleaning rules cannot see passes silently)")
    try:
        sys.exit(main(options))
    except (OSError, pd.errors.ParserError, UnicodeError) as exc:
        print(f"ERROR: cannot read CSV: {exc}")
        sys.exit(2)
