from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.schemas.investor import InvestorResponse


class SignUpRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Name is required")
        return stripped


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class AuthResponse(BaseModel):
    message: str
    investor: InvestorResponse


class ProfileUpdateRequest(BaseModel):
    email: EmailStr | None = None
    username: str | None = Field(default=None, min_length=1, max_length=100)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "ProfileUpdateRequest":
        if self.email is None and self.username is None:
            raise ValueError("At least one of email or username is required")
        return self


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)

    model_config = {"extra": "forbid"}


class ConfirmEmailChangeRequest(BaseModel):
    token: str = Field(min_length=1)

    model_config = {"extra": "forbid"}
