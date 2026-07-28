from pydantic import BaseModel


class SheetConnectionStatus(BaseModel):
    name: str
    sheet_id: str
    connected: bool
    worksheets: list[str] = []
    error: str | None = None


class SheetsStatusResponse(BaseModel):
    sheets: list[SheetConnectionStatus]


class OrphanEntry(BaseModel):
    link_ref_code: str
    present_in: list[str]
    missing_from: list[str]


class DestinationOrphanReport(BaseModel):
    destination: str
    tabs_checked: list[str]
    orphans: list[OrphanEntry]


class OrphanCheckResponse(BaseModel):
    reports: list[DestinationOrphanReport]
