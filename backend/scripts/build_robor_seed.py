"""Build the committed ROBOR seed from a BNR BDI .xlsx export (run locally).

Parses the BNR interactive-database "ROBID - ROBOR - serii zilnice" export
(via bnr_bdi.read_bnr_bdi_xlsx — needs openpyxl, a local-only dependency) and
writes a compact gzipped CSV (date,rate_type,tenor,rate) to
scripts/seeds/robor_history.csv.gz.

That seed is committed + deployed, and load_robor_seed.py loads it into the DB
in any environment using only the standard library (the prod container has no
openpyxl). Re-export a fresh xlsx from
https://bnr.ro/ROBID-ROBOR-5672.aspx (Generează statistică → CSV/Excel) and
re-run this to refresh the seed.

Usage (local, in the venv, from backend/):
    python -m scripts.build_robor_seed /path/to/robid_-_robor_serii_zilnice.xlsx
"""
from __future__ import annotations

import csv
import gzip
import sys
from pathlib import Path

from app.services.rates.bnr_bdi import SEED_CSV_FIELDS, read_bnr_bdi_xlsx

DEFAULT_OUT = Path(__file__).resolve().parent / "seeds" / "robor_history.csv.gz"


def main(xlsx_path: str, out: Path = DEFAULT_OUT) -> int:
    rows = read_bnr_bdi_xlsx(xlsx_path)
    if not rows:
        print(f"[build-seed] no ROBOR rows parsed from {xlsx_path!r}", file=sys.stderr)
        return 1
    rows.sort(key=lambda r: (r.date, r.tenor))
    out.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 → deterministic bytes, so rebuilding the same data is a no-op diff.
    with gzip.GzipFile(filename=str(out), mode="wb", mtime=0) as gz:
        import io

        text = io.TextIOWrapper(gz, newline="", encoding="utf-8")
        w = csv.writer(text)
        w.writerow(SEED_CSV_FIELDS)
        for r in rows:
            w.writerow([r.date, r.rate_type, r.tenor, r.rate])
        text.flush()
        text.detach()
    dates = sorted({r.date for r in rows})
    print(f"[build-seed] wrote {len(rows)} rows ({dates[0]}..{dates[-1]}) -> {out}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m scripts.build_robor_seed <xlsx> [out.csv.gz]", file=sys.stderr)
        raise SystemExit(2)
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    raise SystemExit(main(sys.argv[1], out_path))
