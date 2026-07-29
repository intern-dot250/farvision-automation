import pandas as pd

from app.services import master_repository
from app.services.master_repository import _canonical, _normalize, _strip_master_suffix


def test_strips_paren_code_suffix():
    assert _strip_master_suffix("RAVI VATS(555)") == "RAVI VATS"


def test_strips_space_paren_letter_code():
    assert _strip_master_suffix("RAM KISHAN (C)") == "RAM KISHAN"


def test_strips_dash_and_paren_combo():
    assert _strip_master_suffix("RAHUL KUMAR - CR0198 (AR)") == "RAHUL KUMAR"


def test_no_suffix_is_unchanged():
    assert _strip_master_suffix("SAHIL YADAV") == "SAHIL YADAV"


def test_does_not_strip_real_name_words():
    # "Arvind" must not match this - stripping should leave the real name
    # words ("KUMAR GARG") intact, not just chop to the first word.
    assert _strip_master_suffix("ARVIND KUMAR GARG - CR0446 (AR)") == "ARVIND KUMAR GARG"


def test_normalize_equates_pvt_ltd_and_private_limited():
    assert _normalize("Awesome Paint Planners Pvt Ltd") == _normalize(
        "AWESOME PAINT PLANNERS PRIVATE LIMITED"
    )


def test_normalize_equates_ampersand_and_and():
    assert _normalize("Gupta Paint and Chemical") == _normalize("Gupta Paint & Chemical")


def test_normalize_strips_periods_in_pvt_ltd():
    assert _normalize("XYZ Pvt. Ltd.") == _normalize("XYZ PVT LTD")


def test_normalize_does_not_merge_unrelated_names():
    assert _normalize("Awesome Paint Planners Pvt Ltd") != _normalize(
        "Awesome Paint Traders Private Limited"
    )


def test_canonical_equates_spaced_and_unspaced_initials():
    assert _canonical(_normalize("SN LTD")) == _canonical(_normalize("S N LTD"))
    assert _canonical(_normalize("DK Plywood Pvt Ltd")) == _canonical(_normalize("D K PLYWOOD PVT LTD"))


def test_canonical_equates_ltd_and_pvt_ltd():
    assert _canonical(_normalize("Prayag Polymers Limited")) == _canonical(_normalize("PRAYAG POLYMERS PVT LTD"))


def test_canonical_does_not_merge_unrelated_names():
    assert _canonical(_normalize("SN LTD")) != _canonical(_normalize("RN LTD"))


def test_find_party_matches_via_canonical_form(monkeypatch):
    df = pd.DataFrame.from_records(
        [
            {"Payee Name": "S N LTD", "Account Head": "S N LTD"},
            {"Payee Name": "D K PLYWOOD PVT LTD", "Account Head": "D K PLYWOOD PVT LTD"},
            {"Payee Name": "PRAYAG POLYMERS PVT LTD", "Account Head": "PRAYAG POLYMERS PVT LTD"},
        ]
    )
    monkeypatch.setattr(master_repository, "_load_master_df", lambda: df)

    assert master_repository.find_party("SN Ltd")["Payee Name"] == "S N LTD"
    assert master_repository.find_party("DK Plywood Pvt Ltd")["Payee Name"] == "D K PLYWOOD PVT LTD"
    assert master_repository.find_party("Prayag Polymers Limited")["Payee Name"] == "PRAYAG POLYMERS PVT LTD"
    assert master_repository.find_party("Totally Unrelated Company") is None
