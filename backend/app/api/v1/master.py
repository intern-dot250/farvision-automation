from fastapi import APIRouter

from app.core.constants import Tags
from app.schemas.override_rules import AccountHeadOptionsResponse, HeadOptionsResponse
from app.services import classifier, master_repository

router = APIRouter(prefix="/master", tags=[Tags.SHEETS])

# Heads like "Vendor"/"Contractor"/"Imprest"/"Collection"/"Bank Charges" come
# from the uploaded bank statement's own HEAD column (see classifier.py -
# a trusted existing_head is used as-is, never derived from Master) and are
# never actually present in Master's Parent Account Head text, so they can't
# be discovered by scanning Master alone. Union them with whatever Master
# does yield (via the same _derive_head Master falls back to when there's no
# trusted head) so the dropdown covers both real-world sources.
_KNOWN_HEADS = {"Internal", "Vendor", "Contractor", "Collection", "Imprest", "Bank Charges", "Unclassified"}


@router.get(
    "/heads",
    response_model=HeadOptionsResponse,
    summary="Distinct Head values derivable from Master, for dropdown population",
)
def get_head_options() -> HeadOptionsResponse:
    df = master_repository._load_master_df()
    heads = set(_KNOWN_HEADS)
    for _, row in df.iterrows():
        heads.add(classifier._derive_head(row.to_dict()))
    return HeadOptionsResponse(heads=sorted(h for h in heads if h))


@router.get(
    "/account-heads",
    response_model=AccountHeadOptionsResponse,
    summary="Distinct Account Head values from Master, for dropdown population",
)
def get_account_head_options() -> AccountHeadOptionsResponse:
    df = master_repository._load_master_df()
    if "Account Head" not in df.columns:
        return AccountHeadOptionsResponse(account_heads=[])
    values = df["Account Head"].astype(str).str.strip()
    return AccountHeadOptionsResponse(account_heads=sorted({v for v in values if v}))
