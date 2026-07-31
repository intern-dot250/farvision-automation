from datetime import datetime

from pydantic import BaseModel, Field


class OverrideRuleCreate(BaseModel):
    description_keyword: str = Field(min_length=1)
    head: str = Field(min_length=1)
    sheet_name: str = Field(min_length=1)
    account_head: str = Field(min_length=1)
    is_active: bool = True


class OverrideRuleUpdate(BaseModel):
    description_keyword: str = Field(min_length=1)
    head: str = Field(min_length=1)
    sheet_name: str = Field(min_length=1)
    account_head: str = Field(min_length=1)
    is_active: bool = True


class OverrideRuleToggle(BaseModel):
    is_active: bool


class OverrideRuleResponse(BaseModel):
    id: int
    description_keyword: str
    head: str
    sheet_name: str
    account_head: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class HeadOptionsResponse(BaseModel):
    heads: list[str]


class AccountHeadOptionsResponse(BaseModel):
    account_heads: list[str]
