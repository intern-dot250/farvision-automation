from unittest.mock import patch

from app.services import orphan_checker


def test_check_orphans_finds_code_missing_from_one_tab():
    def fake_get_column_values(sheet_id, worksheet_name, column):
        return {
            "DepositWithdrawal": {"1", "2", "3"},
            "DepositWithdrawalDetails": {"1", "2", "3"},
            "LedgerDetails": {"1", "3"},  # 2 is missing here
        }[worksheet_name]

    with patch(
        "app.services.orphan_checker.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ):
        report = orphan_checker.check_orphans("deposit_withdrawal")

    assert report["destination"] == "deposit_withdrawal"
    assert len(report["orphans"]) == 1
    orphan = report["orphans"][0]
    assert orphan["link_ref_code"] == "2"
    assert orphan["missing_from"] == ["LedgerDetails"]
    assert set(orphan["present_in"]) == {"DepositWithdrawal", "DepositWithdrawalDetails"}


def test_check_orphans_returns_empty_list_when_fully_consistent():
    def fake_get_column_values(sheet_id, worksheet_name, column):
        return {"1", "2", "3"}

    with patch(
        "app.services.orphan_checker.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ):
        report = orphan_checker.check_orphans("deposit_withdrawal")

    assert report["orphans"] == []


def test_check_orphans_sorts_numeric_codes_numerically():
    def fake_get_column_values(sheet_id, worksheet_name, column):
        if worksheet_name == "LedgerDetails":
            return set()
        return {"10", "2", "1"}

    with patch(
        "app.services.orphan_checker.sheets_client.get_column_values",
        side_effect=fake_get_column_values,
    ):
        report = orphan_checker.check_orphans("deposit_withdrawal")

    assert [o["link_ref_code"] for o in report["orphans"]] == ["1", "2", "10"]


def test_check_all_orphans_covers_both_destinations():
    with patch(
        "app.services.orphan_checker.sheets_client.get_column_values",
        return_value=set(),
    ):
        reports = orphan_checker.check_all_orphans()

    destinations = {r["destination"] for r in reports}
    assert destinations == {"deposit_withdrawal", "receipt_payment"}
