#!/usr/bin/env python3
"""
High-level description for non-developers:
This script reads a raw orders export plus a supplier-specific YAML configuration file,
applies filtering/renaming rules defined in that config, and writes the supplier-ready
spreadsheet to an output folder. Think of it as a mail-merge helper that reshapes
Shopify data into exactly what each supplier wants to see.
"""
from __future__ import annotations
import sys, argparse, re
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import yaml

# ---- helpers ----
# Everything below in this section are small utility functions that keep the
# main workflow readable. Each one handles a very specific data-cleanup task.
def to_date(s: str | pd.Timestamp) -> str:
    """Turn any date-like value into a neat 'YYYY-MM-DD' string or an empty string."""
    if pd.isna(s): return ""
    ts = pd.to_datetime(s, errors="coerce", utc=False)
    if pd.isna(ts): return ""
    return ts.strftime("%Y-%m-%d")

def po_date_plus(date_str: str, days: int = 0) -> str:
    """Add a number of days to a purchase-order date so we can express lead times."""
    if not date_str: return ""
    dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")

def concat(*parts):
    """
    Join multiple bits of text into a single clean phrase.
    Example: concat('Blue', 'Size', 'M') -> 'Blue Size M'.
    """
    vals = []
    for p in parts:
        if isinstance(p, str): vals.append(p)
        else: vals.append("" if pd.isna(p) else str(p))
    out = " ".join(x for x in vals if x and x != "nan")
    return re.sub(r"\s+", " ", out).strip()

def normalize_column_name(name: str) -> str:
    """
    Make a column name predictable by lowercasing it and swapping symbols for underscores.
    This lets us compare columns even if the original export used spaces or punctuation.
    """
    return re.sub(r"\W+", "_", name).strip("_").lower()

def load_frame(path: Path) -> pd.DataFrame:
    """
    Open either a CSV or Excel file and hand back a table (pandas DataFrame) where all
    values are treated as text. Treating everything as text avoids surprises like
    ZIP codes losing their leading zeros.
    """
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=str)
    return pd.read_csv(path, dtype=str)

# mini “computed field” executor
def apply_computed(df: pd.DataFrame, computed: dict[str, str]) -> pd.DataFrame:
    """
    Some suppliers need columns that are combinations of other fields (e.g., a label that
    stitches the style code with the size). The configuration file can declare those
    formulas, and this helper evaluates each one row-by-row.
    NOTE: Formulas are trusted input; do not expose this to untrusted configs.
    """
    env = {
        "to_date": to_date,
        "po_date_plus": po_date_plus,
        "concat": concat,
        "pd": pd,
    }
    for col, expr in (computed or {}).items():
        # allowed names are columns and env functions; each row is evaluated separately
        def _eval_row(row):
            local_vars = {k: row.get(k) for k in df.columns}
            local_vars.update(env)
            return eval(expr, {"__builtins__": {}}, local_vars)
        df[col] = df.apply(_eval_row, axis=1)
    return df

# ---- core ----
def transform(orders_path: Path, cfg_path: Path, out_dir: Path) -> Path:
    """
    Heart of the script: read input files, apply configuration rules, validate, then write
    the finished spreadsheet. Returns the path to the file we produced.
    """
    cfg = yaml.safe_load(Path(cfg_path).read_text())
    if cfg is None:
        # Empty configs can happen if someone creates a file but forgets to fill it in.
        raise ValueError("Configuration file is empty; please add the supplier rules.")
    df = load_frame(orders_path)

    # normalize source column names to snake_case
    df.columns = [normalize_column_name(c) for c in df.columns]

    # basic filters
    # This section keeps only the rows the supplier actually cares about, based on
    # statuses and minimum quantities described in their config file.
    flt = cfg.get("filters", {})
    if inc := flt.get("include_financial_status"):
        if "financial_status" not in df.columns:
            raise ValueError("Filter 'include_financial_status' requires 'financial_status' column in source data.")
        status = df["financial_status"].fillna("").astype(str).str.lower()
        df = df[status.isin({s.lower() for s in inc})]
    if exc := flt.get("exclude_fulfillment_status"):
        if "fulfillment_status" not in df.columns:
            raise ValueError("Filter 'exclude_fulfillment_status' requires 'fulfillment_status' column in source data.")
        status = df["fulfillment_status"].fillna("").astype(str).str.lower()
        df = df[~status.isin({s.lower() for s in exc})]
    if (mq := flt.get("min_quantity")) is not None:
        if "lineitem_quantity" in df.columns:
            qcol = "lineitem_quantity"
        elif "qty" in df.columns:
            qcol = "qty"
        else:
            raise ValueError("Filter 'min_quantity' requires either 'lineitem_quantity' or 'qty' column.")
        df[qcol] = pd.to_numeric(df[qcol], errors="coerce").fillna(0).astype(int)
        df = df[df[qcol] >= int(mq)]

    # rename to intermediate normalized names
    # At this point we align varying Shopify column names to the internal names expected
    # by the rest of the script so later steps can rely on consistent labels.
    ren = (cfg.get("mappings", {}) or {}).get("rename", {}) or {}
    df = df.rename(columns={normalize_column_name(k): v for k, v in ren.items() if normalize_column_name(k) in df.columns})

    # computed columns
    # Build any extra columns the supplier requested (e.g., location notes or PO dates).
    df = apply_computed(df, (cfg.get("mappings", {}) or {}).get("computed"))

    # final rename & column order
    # Give the columns their final supplier-facing names and arrange them in the order
    # they expect in their template.
    final_map = (cfg.get("output", {}) or {}).get("rename_final", {}) or {}
    df = df.rename(columns={normalize_column_name(k): v for k, v in final_map.items() if normalize_column_name(k) in df.columns})
    order = (cfg.get("output", {}) or {}).get("columns_order", [])
    if order:
        for c in order:
            if c not in df.columns: df[c] = ""  # ensure exists
        df = df[order]

    # validation
    # Before we ship the file, double-check that columns the supplier marked as required
    # are present, non-empty, and (when needed) positive numbers. This prevents sending
    # incomplete purchase orders.
    val = cfg.get("validation", {}) or {}
    for c in val.get("required", []):
        if c not in df.columns or df[c].isna().any() or (df[c].astype(str).str.strip() == "").any():
            raise ValueError(f"Validation failed: required column '{c}' has missing values.")
    for c in val.get("positive_int", []):
        if c in df.columns:
            if (pd.to_numeric(df[c], errors="coerce") <= 0).any():
                raise ValueError(f"Validation failed: '{c}' must be > 0.")
    for c in val.get("nonempty", []):
        if c in df.columns:
            if (df[c].astype(str).str.strip() == "").any():
                raise ValueError(f"Validation failed: '{c}' has empty values.")

    # write output
    # Name the file using today's date (or the supplier's custom pattern) and export it
    # either as CSV or Excel depending on the config setting.
    today = datetime.now().strftime("%Y%m%d")
    delivery = cfg.get("delivery", {}) or {}
    fmt = (delivery.get("format") or "csv").lower()
    filename = (delivery.get("filename_pattern") or f"supplier_{today}.csv").replace("{today}", today)
    out_path = out_dir / filename
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt == "xlsx":
        df.to_excel(out_path, index=False)
    else:
        df.to_csv(out_path, index=False)
    return out_path

def main():
    """
    Wire up the command-line interface so someone can run:
      python orders_to_suppliers.py --orders raw.csv --config supplier.yaml --outdir out/
    """
    ap = argparse.ArgumentParser(description="Orders → Supplier transformer (config-driven)")
    ap.add_argument("--orders", required=True, type=Path, help="Path to orders export (CSV/XLSX)")
    ap.add_argument("--config", required=True, type=Path, help="Supplier YAML config")
    ap.add_argument("--outdir", default=Path("out"), type=Path, help="Output directory")
    args = ap.parse_args()
    out = transform(args.orders, args.config, args.outdir)
    print(f"Wrote: {out}")

if __name__ == "__main__":
    sys.exit(main())
