"""FastAPI dependencies for authentication and authorization middleware."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository

# We use the standard OAuth2 Bearer scheme to extract the token from the header.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"/api/v1/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Decode JWT, fetch the user, and inject it into the route.
    
    If the token is invalid, expired, or the user is disabled/deleted,
    this dependency aborts the request with an HTTP 401.
    """
    settings = get_settings()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    user_repo = UserRepository(session)
    user = await user_repo.get_by_id_or_raise(int(user_id))
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user account",
        )
        
    return user


class RequireRole:
    """FastAPI Dependency for Role-Based Access Control.
    
    Usage:
        @router.get("/", dependencies=[Depends(RequireRole(["Admin", "Manager"]))])
    """

    def __init__(self, allowed_roles: list[str]) -> None:
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: Annotated[User, Depends(get_current_user)]) -> User:
        user_roles = [role.name for role in current_user.roles]
        
        # If they are a global Admin, they always pass.
        if "Admin" in user_roles:
            return current_user
            
        has_role = any(role in self.allowed_roles for role in user_roles)
        if not has_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have the necessary roles to access this resource.",
            )
            
        return current_user


class RequirePermission:
    """FastAPI Dependency for Fine-Grained Permission Access Control.
    
    Usage:
        @router.post("/", dependencies=[Depends(RequirePermission(["sprint:write"]))])
    """

    def __init__(self, required_permissions: list[str]) -> None:
        self.required_permissions = required_permissions

    def __call__(self, current_user: Annotated[User, Depends(get_current_user)]) -> User:
        user_roles = [role.name for role in current_user.roles]
        if "Admin" in user_roles:
            return current_user
            
        # Flatten all permissions from all roles the user has
        user_permissions = []
        for role in current_user.roles:
            for perm in role.permissions:
                user_permissions.append(perm.code)
                
        # Must have ALL required permissions
        has_all_perms = all(req in user_permissions for req in self.required_permissions)
        
        if not has_all_perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have the necessary permissions to access this resource.",
            )
            
        return current_user
