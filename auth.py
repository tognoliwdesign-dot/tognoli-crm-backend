"""LEXARYS — Authentification JWT"""
import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from database import supabase
from models import UserCreate

SECRET_KEY = os.getenv("SECRET_KEY", "lexarys-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

router = APIRouter(prefix="/auth", tags=["auth"])

def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
def hash_password(password): return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    exc = HTTPException(status_code=401, detail="Token invalide ou expiré", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id: raise exc
    except JWTError:
        raise exc
    result = supabase.table("users").select("*").eq("id", user_id).single().execute()
    if not result.data: raise exc
    return result.data

@router.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    result = supabase.table("users").select("*").eq("email", form_data.username).single().execute()
    if not result.data: raise HTTPException(401, "Identifiants incorrects")
    user = result.data
    if not verify_password(form_data.password, user.get("password_hash", "")): raise HTTPException(401, "Identifiants incorrects")
    token = create_access_token({"sub": user["id"]})
    return {"access_token": token, "token_type": "bearer", "user": {"id": user["id"], "email": user["email"], "first_name": user.get("first_name"), "last_name": user.get("last_name"), "role": user.get("role", "avocat"), "barreau": user.get("barreau")}}

@router.post("/register")
async def register(body: UserCreate):
    existing = supabase.table("users").select("id").eq("email", body.email).execute()
    if existing.data: raise HTTPException(400, "Email déjà utilisé")
    data = {"email": body.email, "password_hash": hash_password(body.password), "first_name": body.first_name, "last_name": body.last_name, "role": body.role or "avocat", "barreau": body.barreau}
    result = supabase.table("users").insert(data).execute()
    user = result.data[0] if result.data else {}
    token = create_access_token({"sub": user.get("id", "")})
    return {"access_token": token, "token_type": "bearer", "user": user}

@router.put("/change-password")
async def change_password(body: dict, user=Depends(get_current_user)):
    new_pwd = body.get("password")
    if not new_pwd or len(new_pwd) < 6: raise HTTPException(400, "Mot de passe trop court")
    supabase.table("users").update({"password_hash": hash_password(new_pwd)}).eq("id", user["id"]).execute()
    return {"success": True}

@router.get("/me")
async def me(user=Depends(get_current_user)):
    return user
