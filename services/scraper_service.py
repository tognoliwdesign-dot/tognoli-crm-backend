import asyncio
import random
import re
import httpx
from bs4 import BeautifulSoup

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

def _get_headers():
    return {"User-Agent": random.choice(USER_AGENTS), "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7", "DNT": "1"}

async def scrape_google_leads(sector: str, city: str, country: str = "France", max_results: int = 20) -> list:
    leads = []
    queries = [f'"{sector}" "{city}" site:linkedin.com/company', f'{sector} {city} {country} entreprise contact', f'"{sector}" {city} "nous contacter" OR "contact@"']
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for query in queries:
            if len(leads) >= max_results:
                break
            try:
                await asyncio.sleep(random.uniform(2, 5))
                response = await client.get(f"https://www.google.com/search?q={query}&num=20&hl=fr", headers=_get_headers())
                if response.status_code != 200:
                    continue
                soup = BeautifulSoup(response.text, "lxml")
                for result in soup.select("div.g"):
                    if len(leads) >= max_results:
                        break
                    try:
                        title_el = result.select_one("h3")
                        link_el = result.select_one("a[href]")
                        snippet_el = result.select_one(".VwiC3b, .s3v9rd")
                        if not title_el or not link_el:
                            continue
                        title = title_el.get_text(strip=True)
                        link = link_el.get("href", "")
                        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                        if not link.startswith("http"):
                            continue
                        if any(l.get("website") == link for l in leads):
                            continue
                        email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', snippet)
                        leads.append({"company_name": _clean_company_name(title), "website": link, "sector": sector, "city": city, "country": country, "email": email_match.group(0) if email_match else "", "notes": snippet[:200], "source": "google_scraper", "score": 30, "status": "new"})
                    except Exception:
                        continue
            except Exception as e:
                print(f"Scraper error: {e}")
                continue
    seen = set()
    unique = []
    for lead in leads:
        key = lead["company_name"].lower()
        if key not in seen and len(key) > 2:
            seen.add(key)
            unique.append(lead)
    return unique[:max_results]

def _clean_company_name(title: str) -> str:
    for suffix in [" - LinkedIn", " | LinkedIn", " - Facebook", " - Accueil", " - Site officiel"]:
        title = title.replace(suffix, "")
    title = re.sub(r'\s*-\s*www\.[^\s]+', '', title)
    return title.strip()[:100]
