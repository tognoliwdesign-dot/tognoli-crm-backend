from fastapi import APIRouter, Depends, HTTPException
from auth import get_current_user
from database import get_admin_client
from models import ScraperRequest
from services.scraper_service import scrape_google_leads

router = APIRouter()

@router.post("/search")
async def search_leads(body: ScraperRequest, current_user: dict = Depends(get_current_user)):
    db = get_admin_client()
    count_result = db.table("leads").select("id", count="exact").eq("user_id", current_user["id"]).execute()
    current_count = count_result.count or 0
    lead_limit = current_user.get("lead_limit", 100)
    available = lead_limit - current_count
    if available <= 0:
        raise HTTPException(status_code=403, detail=f"Limite de {lead_limit} leads atteinte")
    max_results = min(body.max_results, available, 20)
    scraped = await scrape_google_leads(sector=body.sector, city=body.city, country=body.country, max_results=max_results)
    if not scraped:
        return {"found": 0, "imported": 0, "leads": [], "message": "Aucun résultat trouvé. Essayez d'autres termes."}
    for lead in scraped:
        lead["user_id"] = current_user["id"]
    result = db.table("leads").insert(scraped).execute()
    imported = len(result.data) if result.data else 0
    return {"found": len(scraped), "imported": imported, "leads": result.data or [], "message": f"{imported} leads importés depuis Google"}

@router.get("/preview")
async def preview_search(sector: str, city: str, country: str = "France", current_user: dict = Depends(get_current_user)):
    scraped = await scrape_google_leads(sector=sector, city=city, country=country, max_results=5)
    return {"preview": scraped, "count": len(scraped)}
