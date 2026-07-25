"""One-off: backfill processed_transactions for the 12 transactions written
in Phase 7, before Supabase-based duplicate detection existed. Without this,
the next automation run would re-detect them as new and duplicate them.

Run from backend/ so .env resolves correctly:
    cd backend && .venv/Scripts/python.exe ../scripts/backfill_processed_transactions.py
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.services import ledger_repository  # noqa: E402

ALREADY_WRITTEN = [
    {"sl_no": "336", "reference": "YESME6203001855900", "head": "Contractor", "destination": "receipt_payment", "link_ref_code": 3},
    {"sl_no": "335", "reference": "YESME6203001855800", "head": "Contractor", "destination": "receipt_payment", "link_ref_code": 4},
    {"sl_no": "334", "reference": "YESME6203001855700", "head": "Contractor", "destination": "receipt_payment", "link_ref_code": 5},
    {"sl_no": "333", "reference": "YESME6203001855600", "head": "Contractor", "destination": "receipt_payment", "link_ref_code": 6},
    {"sl_no": "332", "reference": "YESME6203001855500", "head": "Contractor", "destination": "receipt_payment", "link_ref_code": 7},
    {"sl_no": "330", "reference": "YESME6203001670300", "head": "Contractor", "destination": "receipt_payment", "link_ref_code": 8},
    {"sl_no": "329", "reference": "YESME6203001855400", "head": "SUNDRY CREDITORS - PROFESSIONAL FEES", "destination": "receipt_payment", "link_ref_code": 9},
    {"sl_no": "328", "reference": "YESME6203001855300", "head": "Contractor", "destination": "receipt_payment", "link_ref_code": 10},
    {"sl_no": "327", "reference": "YESME6203001669900", "head": "SUNDRY CREDITORS - OTHER", "destination": "receipt_payment", "link_ref_code": 11},
    {"sl_no": "326", "reference": "YESME6203001670000", "head": "SUNDRY CREDITORS - OTHER", "destination": "receipt_payment", "link_ref_code": 12},
    {"sl_no": "325", "reference": "YESME6203001321900", "head": "Internal", "destination": "deposit_withdrawal", "link_ref_code": 2},
    {"sl_no": "324", "reference": "YESME6201006466000", "head": "Internal", "destination": "deposit_withdrawal", "link_ref_code": 3},
]


def main() -> None:
    for entry in ALREADY_WRITTEN:
        if ledger_repository.is_already_processed(entry["reference"]):
            print(f"skip (already backfilled): {entry['reference']}")
            continue

        ledger_repository.mark_processed(
            reference=entry["reference"],
            sl_no=entry["sl_no"],
            description="",
            head=entry["head"],
            destination=entry["destination"],
            link_ref_code=entry["link_ref_code"],
        )
        print(f"backfilled: {entry['reference']} (SL#{entry['sl_no']})")


if __name__ == "__main__":
    main()
