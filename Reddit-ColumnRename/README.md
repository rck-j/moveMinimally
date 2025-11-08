# Supplier Export Automation (inspired by Reddit thread)

> “Every time I export orders I have to rename columns, delete fields, and format everything so the supplier can process it. It’s hours of repetitive cleanup each week.” — small biz owner on Reddit

This repo is a direct response to that pain. Instead of fixing every spreadsheet by hand, you describe what your supplier wants in a simple YAML file, then run one script that does the filtering, renaming, and reformatting for you. The full backstory and build notes live in [this blog post](https://moveminimally.com/every-week-small-business-owners-lose-hours-cleaning-up-spreadsheet-exports-renaming-columns-deleting-unnecessary-fields-and-reformatting-order-data-so-their-suppliers-can-actually-use/).

## Prerequisites

- Python 3.10+ installed locally.
- `pip install -r requirements.txt` (or directly `pip install pandas pyyaml openpyxl`).
- A raw Shopify/Shopify-like order export (CSV or XLSX).
- A supplier config (see `configs/supplier_acme.yaml` for a heavily commented example).

## Folder layout

```
Reddit-ColumnRename/
├── configs/                 # all supplier YAML configs live here
├── exports/                 # drop raw order exports here (anywhere works; this keeps things tidy)
├── out/                     # script writes finished supplier files here
├── scripts/orders_to_suppliers.py
└── README.md
```

Feel free to rename folders; just update the paths you pass to the script.

## Step-by-step: run `orders_to_suppliers.py`

1. **Prep your inputs**
   - Save the latest orders export to `exports/YourFile.csv` (CSV or Excel).
   - Copy `configs/supplier_acme.yaml` and edit it until the sample comments match what your supplier expects (column names, formulas, column order, etc.).

2. **Run the transformer**

   ```bash
   cd Reddit-ColumnRename
   python3 scripts/orders_to_suppliers.py \
     --orders exports/Sample_Orders_Export__shop_orders_sample_csv_.csv \
     --config configs/supplier_acme.yaml \
     --outdir out
   ```

   - `--orders` points to your raw export.
   - `--config` points to the YAML file you tailored for the supplier.
   - `--outdir` is where the cleaned file will be written (defaults to `out/` if omitted).

3. **Open the result**
   - The script prints the exact file name it wrote (e.g., `out/ACME_PO_20231107.csv`).
   - Review it once, then send it along—no manual column juggling needed.

## Extending to new suppliers

1. Duplicate `configs/supplier_acme.yaml` to `configs/supplier_<name>.yaml`.
2. Follow the numbered instructions in `mappings.rename` and `output.rename_final` comments to add/rename columns.
3. Run the same Python command, swapping `--config` for the new file.

## Troubleshooting tips

- “Missing column” errors mean the CSV header doesn’t match what the YAML references—double-check spelling/casing.
- Need Excel output? Set `delivery.format: "xlsx"` in the config.
- Add more filters (e.g., fulfillment status) in the `filters` block; the script explains each option in comments.

Once you have configs per supplier, the weekly manual cleanup from the Reddit post becomes a single CLI command. Feel free to adapt the script or configs to your workflow and share improvements! 
