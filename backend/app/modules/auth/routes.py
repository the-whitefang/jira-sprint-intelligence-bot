"""REST API routes for authentication and session management."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.modules.auth.dependencies import get_current_user, RequireRole
from app.modules.auth.models import User
from app.modules.auth.schemas import LoginRequest, TokenResponse, UserResponse
from app.modules.auth.service import AuthService, get_auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenResponse:
    """Authenticate a user and return a JWT access token."""
    user = await auth_service.authenticate_user(payload)
    return await auth_service.generate_token_response(user)


@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Return the profile and permissions of the currently authenticated user."""
    # We flatten permissions so the frontend can easily read them
    flat_permissions = []
    for role in current_user.roles:
        for perm in role.permissions:
            flat_permissions.append(perm.code)
            
    response_data = {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "jira_account_id": current_user.jira_account_id,
        "roles": current_user.roles,
        "permissions": flat_permissions,
    }
    return UserResponse.model_validate(response_data)


# Example of an RBAC-protected endpoint
@router.get("/admin-only")
async def secure_admin_ping(
    current_user: Annotated[User, Depends(RequireRole(["Admin"]))],
) -> dict[str, str]:
    """Test endpoint demonstrating Role-Based Access Control."""
    return {"message": "You have accessed an Admin-only route!"}
