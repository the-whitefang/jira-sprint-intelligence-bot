"""Authentication and session management logic."""

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.auth.schemas import LoginRequest, TokenResponse


class AuthService:
    """Service isolating identity and authentication logic."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._user_repo = UserRepository(session)

    async def authenticate_user(self, payload: LoginRequest) -> User:
        """Verify user credentials and return the loaded User if valid.
        
        Raises:
            HTTPException(401): If credentials are invalid.
        """
        user = await self._user_repo.get_by_email(payload.email)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        if not verify_password(payload.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        return user

    async def generate_token_response(self, user: User) -> TokenResponse:
        """Generate a standard OAuth2 token response for an authenticated user."""
        settings = get_settings()
        
        # In a real app we'd also generate/store a Refresh Token here,
        # but to keep the tutorial lightweight we will just issue the access token.
        roles = [role.name for role in user.roles]
        
        token = create_access_token(
            subject=user.id,
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            roles=roles,
        )
        
        return TokenResponse(
            access_token=token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )


def get_auth_service(session: Annotated[AsyncSession, Depends(get_db)]) -> AuthService:
    """Dependency injector for AuthService."""
    return AuthService(session)
