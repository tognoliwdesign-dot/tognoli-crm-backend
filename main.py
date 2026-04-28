import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from database import create_tables
from auth import router as auth_router, hash_password
from routes.admin import router as admin_router
from routes.leads import router as leads_router
from routes.ai import router as ai_router
from routes.email_routes import router as email_router
from routes.scraper import router as scraper_router
from routes.stripe_routes import router as stripe_router


async def create_admin_if_missing():
    try:
        from database import get_admin_client
        admin_email = os.getenv("ADMIN_EMAIL", "tognoli.wdesign@gmail.com")
        admin_password = os.getenv("ADMIN_PASSWORD", "StognoliTwd12!")
        db = get_admin_client()
        existing = db.table("users").select("id").eq("email", admin_email).execute()
        if not existing.data:
            db.table("users").insert({
                "email": admin_email,
                "password_hash": hash_password(admin_password),
                "role": "admin",
                "company_name": "TOGNOLI Web-Design",
                "lead_limit": 99999,
                "is_active": True,
                "subscription_status": "active",
            }).execute()
            print(f"✅ Compte admin créé: {admin_email}")
        else:
            print(f"✅ Admin existant: {admin_email}")
    except Exception as e:
        print(f"⚠️  Admin setup: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    await create_admin_if_missing()
    print("🚀 TOGNOLI CRM AI - Backend démarré")
    yield


app = FastAPI(
    title="TOGNOLI CRM AI",
    description="CRM SaaS B2B avec IA pour la prospection et la gestion de leads",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth", tags=["Authentification"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])
app.include_router(leads_router, prefix="/leads", tags=["Leads"])
app.include_router(ai_router, prefix="/ai", tags=["Intelligence Artificielle"])
app.include_router(email_router, prefix="/email", tags=["Email"])
app.include_router(scraper_router, prefix="/scraper", tags=["Scraper"])
app.include_router(stripe_router, prefix="/stripe", tags=["Stripe"])


@app.get("/")
async def root():
    return {"app": "TOGNOLI CRM AI", "version": "1.0.0", "status": "online", "docs": "/docs"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
