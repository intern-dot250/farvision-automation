from pydantic import BaseModel


class SheetConnectionStatus(BaseModel):
    name: str
    sheet_id: str
    connected: bool
    worksheets: list[str] = []
    error: str | None = None


class SheetsStatusResponse(BaseModel):
    sheets: list[SheetConnectionStatus]
