from pydantic import BaseModel, EmailStr, ConfigDict


class LoginRequest(BaseModel):
    """Payload for user login."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Standard OAuth2 token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RoleResponse(BaseModel):
    """Role information."""
    name: str

    model_config = ConfigDict(from_attributes=True)


class PermissionResponse(BaseModel):
    """Permission information."""
    code: str

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    """User profile response."""
    id: int
    email: EmailStr
    full_name: str
    jira_account_id: str | None = None
    roles: list[RoleResponse] = []
    
    # We flatten permissions into a simple list of codes for the frontend
    permissions: list[str] = []

    model_config = ConfigDict(from_attributes=True)
