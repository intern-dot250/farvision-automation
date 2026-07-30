import io

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_sheet_names_route_returns_candidate_sheets():
    import pandas as pd

    df = pd.DataFrame(
        [
            {
                "SL#": "1",
                "TXN DATE": "22-Jul-2026",
                "DESCRIPTION": "desc",
                "REFERENCE": "REF1",
                "DEBITS": "1000",
                "CREDITS": "",
            }
        ]
    )
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        df.to_excel(writer, sheet_name="YES Rera 0377", index=False)
        pd.DataFrame([{"unrelated": "no transaction columns"}]).to_excel(
            writer, sheet_name="Index", index=False
        )
    content = buffer.getvalue()

    response = client.post(
        "/api/v1/automation/sheet-names",
        files={"file": ("statement.xlsx", content, "application/vnd.ms-excel")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "sheets": ["YES Rera 0377"],
        "total_sheets": 2,
        "ignored_sheets": ["Index"],
    }


def test_sheet_names_route_returns_empty_for_csv():
    response = client.post(
        "/api/v1/automation/sheet-names",
        files={"file": ("statement.csv", b"a,b\n1,2\n", "text/csv")},
    )

    assert response.status_code == 200
    assert response.json() == {"sheets": [], "total_sheets": 0, "ignored_sheets": []}
