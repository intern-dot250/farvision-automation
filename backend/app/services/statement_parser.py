import io

import pandas as pd

REQUIRED_COLUMNS = ["TXN DATE", "DESCRIPTION", "REFERENCE", "DEBITS", "CREDITS"]


def parse_statement_file(filename: str, content: bytes) -> list[dict]:
    """Parse an uploaded bank statement file into the same row-shape used
    when reading from the Google Sheet (same column names), so it can feed
    the same classify/route/write pipeline unchanged.
    """
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content), dtype=str)
    else:
        df = pd.read_excel(io.BytesIO(content), dtype=str)

    df = df.fillna("")

    missing = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Uploaded file is missing required columns: {', '.join(missing)}")

    return df.to_dict(orient="records")
