"""Dev utility: dump headers + sample rows for every tab in the 3 configured sheets.

Run from backend/ so .env resolves correctly:
    cd backend && .venv/Scripts/python.exe ../scripts/inspect_sheets.py
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.services import sheets_client  # noqa: E402


def inspect(sheet_id: str, label: str) -> None:
    print(f"\n{'=' * 60}\n{label} ({sheet_id})\n{'=' * 60}")
    sheet = sheets_client.open_sheet(sheet_id)
    for worksheet in sheet.worksheets():
        print(f"\n--- tab: {worksheet.title} ---")
        rows = worksheet.get_all_values()
        if not rows:
            print("(empty)")
            continue
        print("headers:", rows[0])
        for row in rows[1:4]:
            print("row:", row)
        print(f"(total rows: {len(rows) - 1})")


def main() -> None:
    settings = get_settings()
    inspect(settings.STATEMENT_MASTER_SHEET_ID, "Statement / Master")
    inspect(settings.DEPOSIT_WITHDRAWAL_SHEET_ID, "Deposit / Withdrawal")
    inspect(settings.RECEIPT_PAYMENT_SHEET_ID, "Receipt / Payment")


if __name__ == "__main__":
    main()
