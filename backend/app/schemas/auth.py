from pydantic import BaseModel, Field


class VerifyPasswordRequest(BaseModel):
    password: str


class VerifyPasswordResponse(BaseModel):
    valid: bool


class SetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8)


class SetPasswordResponse(BaseModel):
    success: bool
