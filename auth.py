"""LEXARYS - Authentification JWT"""
import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from database import supabase
from models import UserCreate, LoginRequest

SECRET_KEY = os.getenv("SECRET_KEY", "lexarys-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 jours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

router = APIRouter(prefix="/auth", tags=["auth"])


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expire",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    try:
        # Utiliser execute() sans single() pour eviter les exceptions
        result = supabase.table("users").select("*").eq("id", user_id).execute()
        if not result.data:
            raise credentials_exception
        return result.data[0]
    except HTTPException:
        raise
    except Exception:
        raise credentials_exception


@router.post("/login")
async def login(body: LoginRequest):
    result = supabase.table("users").select("*").eq("email", body.email).execute()
    if not result.data:
        raise HTTPException(status_code=401, detail="Identifiants incorrects")

    user = result.data[0]
    if not user.get("is_active", True):
        raise HTTPException(status_code=401, detail="Compte desactive")
    if not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")

    access_token = create_access_token(data={"sub": user["id"]})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user.get("full_name"),
            "role": user.get("role", "avocat"),
            "barreau": user.get("barreau"),
            "lead_limit": user.get("lead_limit", 500),
            "subscription_status": user.get("subscription_status", "trial"),
            "features_enabled": user.get("features_enabled"),
        }
    }


@router.post("/register")
async def register(body: UserCreate):
    existing = supabase.table("users").select("id").eq("email", body.email).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Email deja utilise")

    data = {
        "email": body.email,
        "password_hash": hash_password(body.password),
        "full_name": body.full_name,
        "role": body.role or "avocat",
        "barreau": body.barreau,
        "specialites": body.specialites or [],
    }
    result = supabase.table("users").insert(data).execute()
    user = result.data[0] if result.data else {}
    access_token = create_access_token(data={"sub": user["id"]})
    return {"access_token": access_token, "token_type": "bearer", "user": user}


@router.put("/change-password")
async def change_password(body: dict, user=Depends(get_current_user)):
    new_pwd = body.get("password")
    if not new_pwd or len(new_pwd) < 6:
        raise HTTPException(status_code=400, detail="Mot de passe trop court")
    supabase.table("users").update({"password_hash": hash_password(new_pwd)}).eq("id", user["id"]).execute()
    return {"success": True}


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return user
