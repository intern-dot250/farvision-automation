from app.services.master_repository import _normalize, _strip_master_suffix


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
