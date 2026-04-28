import os
import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "mistralai/mistral-7b-instruct"

async def call_ai(system_prompt: str, user_prompt: str) -> str:
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "HTTP-Referer": "https://crm-tognoli.com", "X-Title": "TOGNOLI CRM AI"}
    payload = {"model": MODEL, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], "max_tokens": 800, "temperature": 0.7}
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(OPENROUTER_URL, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

async def generate_cold_email(lead: dict, tone: str = "professionnel", language: str = "fr") -> str:
    system = f"Tu es un expert en prospection B2B. Tu rédiges des emails de prospection percutants, personnalisés et efficaces en {language}. Ton: {tone}. L'email doit être court (150-200 mots), avec une accroche personnalisée, une proposition de valeur claire et un call-to-action précis."
    user = f"Rédige un email de prospection pour cette entreprise:\n- Entreprise: {lead.get('company_name', '')}\n- Contact: {lead.get('contact_name', '')}\n- Secteur: {lead.get('sector', '')}\n- Ville: {lead.get('city', '')}\n- Site web: {lead.get('website', '')}\n- Notes: {lead.get('notes', '')}\n\nFormat:\nObjet: [objet]\n---\n[corps de l'email]"
    return await call_ai(system, user)

async def generate_followup(lead: dict, days: int = 7) -> str:
    system = "Tu es un expert en relance commerciale B2B. Tu rédiges des emails de relance professionnels, non-intrusifs et efficaces."
    user = f"Rédige un email de relance pour cette entreprise (premier contact il y a {days} jours):\n- Entreprise: {lead.get('company_name', '')}\n- Contact: {lead.get('contact_name', '')}\n- Secteur: {lead.get('sector', '')}\n- Status actuel: {lead.get('status', 'contacté')}\n- Notes: {lead.get('notes', '')}\n\nFormat:\nObjet: [objet]\n---\n[corps de l'email]"
    return await call_ai(system, user)

async def score_lead(lead: dict) -> dict:
    system = "Tu es un expert en qualification de leads B2B. Tu analyses les informations d'un prospect et tu attribues un score de 0 à 100 avec une justification détaillée."
    user = f"Score ce lead B2B de 0 à 100:\n- Entreprise: {lead.get('company_name', '')}\n- Contact: {lead.get('contact_name', '')}\n- Email: {'✓' if lead.get('email') else '✗'}\n- Téléphone: {'✓' if lead.get('phone') else '✗'}\n- Site web: {lead.get('website', 'Non renseigné')}\n- Secteur: {lead.get('sector', '')}\n\nRéponds EXACTEMENT dans ce format JSON:\n{{\"score\": 75, \"niveau\": \"Chaud\", \"points_forts\": [\"point1\"], \"points_faibles\": [\"point1\"], \"recommandation\": \"action\"}}"
    result = await call_ai(system, user)
    import json, re
    try:
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception:
        pass
    return {"score": 50, "niveau": "Tiède", "points_forts": [], "points_faibles": [], "recommandation": result}

async def generate_linkedin_message(lead: dict) -> str:
    system = "Tu es un expert en networking LinkedIn B2B. Tu rédiges des messages de connexion et de prospection courts (300 caractères max), personnalisés et non-commerciaux."
    user = f"Rédige un message LinkedIn de prospection pour:\n- Entreprise: {lead.get('company_name', '')}\n- Contact: {lead.get('contact_name', '')}\n- Secteur: {lead.get('sector', '')}\n\nFormat:\nMessage de connexion (300 car. max): [message]\n---\nMessage de suivi (500 car. max): [message]"
    return await call_ai(system, user)
