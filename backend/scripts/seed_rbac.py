"""Idempotent seed script for RBAC (Roles and Permissions)."""

import asyncio
import sys
import os

# Ensure backend directory is in python path
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import select
from app.db.session import init_engine, async_session_factory
from app.core.config import get_settings
from app.modules.auth.models import Role, Permission, User
from app.core.security import get_password_hash


ROLES_AND_PERMISSIONS = {
    "Admin": [
        "sprint:read", "sprint:write", "sprint:delete",
        "user:read", "user:write", "user:delete",
        "settings:write", "chat:use"
    ],
    "Manager": [
        "sprint:read", "sprint:write",
        "user:read",
        "chat:use"
    ],
    "Developer": [
        "sprint:read",
        "chat:use"
    ],
    "Viewer": [
        "sprint:read"
    ]
}


async def seed_rbac() -> None:
    settings = get_settings()
    init_engine(settings)

    admin_password = os.getenv("DEFAULT_ADMIN_PASSWORD")
    
    if not admin_password:
        raise RuntimeError("DEFAULT_ADMIN_PASSWORD is not configured")

    async with async_session_factory() as session:
        print("Seeding RBAC roles and permissions...")
        
        # 1. Ensure all permissions exist
        all_perms_needed = {p for perms in ROLES_AND_PERMISSIONS.values() for p in perms}
        
        # Fetch existing perms
        result = await session.execute(select(Permission))
        existing_perms = {p.code: p for p in result.scalars()}
        
        # Create missing perms
        for code in all_perms_needed:
            if code not in existing_perms:
                perm = Permission(code=code, description=f"Grants {code} access")
                session.add(perm)
                existing_perms[code] = perm
                
        await session.flush()
        
        # 2. Ensure all roles exist and map to right permissions
        result = await session.execute(select(Role))
        existing_roles = {r.name: r for r in result.scalars()}
        
        for role_name, perm_codes in ROLES_AND_PERMISSIONS.items():
            if role_name not in existing_roles:
                role = Role(name=role_name)
                session.add(role)
                existing_roles[role_name] = role
                
            role = existing_roles[role_name]
            # Ensure permissions are synced (using eager loaded or manual)
            # For simplicity in this script, we just append missing
            # (In a real sync, we'd clear and reset)
            role.permissions = [existing_perms[c] for c in perm_codes]
            
        await session.flush()
        
        # 3. Create a default Admin user if none exists
        admin_email = "admin@jsibot.local"
        result = await session.execute(select(User).where(User.email == admin_email))
        admin_user = result.scalar_one_or_none()
        
        if not admin_user:
            print("Creating default admin account (admin@jsibot.local)")
            admin_user = User(
                email=admin_email,
                password_hash=get_password_hash(admin_password),
                full_name="System Administrator",
                is_active=True
            )
            admin_user.roles = [existing_roles["Admin"]]
            session.add(admin_user)
            
        await session.commit()
        print("✅ RBAC seeding completed.")

if __name__ == "__main__":
    asyncio.run(seed_rbac())
