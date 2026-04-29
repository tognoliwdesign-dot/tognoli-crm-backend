"""LEXARYS — Route Scraper"""
from fastapi import APIRouter, Query, Depends
from auth import get_current_user
from services.sirene import search_sirene, get_bodacc, enrich_prospect

router = APIRouter(prefix="/scraper", tags=["scraper"])

@router.get("/sirene")
async def scrape_sirene(q: str = Query(...), postal_code: str = None, limit: int = 10, user=Depends(get_current_user)):
    return await search_sirene(q, postal_code=postal_code, limit=limit)

@router.get("/bodacc/{siren}")
async def scrape_bodacc(siren: str, user=Depends(get_current_user)):
    return await get_bodacc(siren)

@router.get("/enrich")
async def scrape_enrich(siren: str = None, siret: str = None, user=Depends(get_current_user)):
    return await enrich_prospect(siren=siren, siret=siret)
