from app.services import sheets_client


def get_next_ref_code(sheet_id: str, worksheet_name: str, column_name: str = "Link Ref Code") -> int:
    """Next Link Ref Code, continuing from the current max value in the sheet (confirmed rule)."""
    records = sheets_client.read_all_records(sheet_id, worksheet_name)
    existing = [
        int(record[column_name])
        for record in records
        if str(record.get(column_name, "")).strip().isdigit()
    ]
    return max(existing, default=0) + 1
