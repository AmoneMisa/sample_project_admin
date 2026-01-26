from fastapi import Depends, HTTPException
from ..routers.auth import get_current_user
from ..models.models import User

def require_user(current_user: User = Depends(get_current_user)):
    return current_user

def require_editor(current_user: User = Depends(get_current_user)):
    if current_user.role not in ("moderator", "admin"):
        raise HTTPException(403, "Недостаточно прав")
    return current_user

def require_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(403, "Только для администратора")
    return current_user

def require_permission(section: str, action: str):
    def dep(current_user: User = Depends(get_current_user)):
        if current_user.role == "admin":
            return current_user
        perms = current_user.permissions or {}
        if not perms.get(section, {}).get(action, False):
            raise HTTPException(403, "Недостаточно прав")
        return current_user
    return dep
