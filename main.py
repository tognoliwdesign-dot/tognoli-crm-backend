"""LEXARYS - Backend FastAPI"""
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from database import create_tables, create_admin_if_missing
from auth import router as auth_router
from routes.prospects import router as prospects_router
from routes.clients import router as clients_router
from routes.dossiers import router as dossiers_router
from routes.conflicts import router as conflicts_router
from routes.admin import router as admin_router
from routes.scraper import router as scraper_router
from services.sirene import search_sirene, get_bodacc, enrich_prospect

@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    await create_admin_if_missing()
    print("LEXARYS - Backend démarré")
    yield

app = FastAPI(title="Lexarys API", description="Logiciel de prospection client pour avocats - conforme RIN", version="1.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["https://tognoliwdesign-dot.github.io", "http://localhost:3000", "http://localhost:8080"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

app.include_router(auth_router)
app.include_router(prospects_router)
app.include_router(clients_router)
app.include_router(dossiers_router)
app.include_router(conflicts_router)
app.include_router(admin_router)
app.include_router(scraper_router)

@app.get("/")
def root(): return {"name": "Lexarys API", "version": "1.0.0", "status": "running"}

@app.get("/health")
def health(): return {"status": "ok"}

@app.get("/sirene/search")
async def sirene_search(q: str = Query(...), postal_code: str = None, limit: int = 10):
    return await search_sirene(q, postal_code=postal_code, limit=limit)

@app.get("/bodacc/{siren}")
async def bodacc_lookup(siren: str):
    return await get_bodacc(siren)

@app.get("/enrich")
async def enrich(siren: str = None, siret: str = None):
    return await enrich_prospect(siren=siren, siret=siret)
