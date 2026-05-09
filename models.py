"""LEXARYS — Modeles Pydantic (noms FR + EN acceptes)"""
from pydantic import BaseModel, EmailStr
from typing import Optional, List, Any
from datetime import date, datetime


# Auth
class LoginRequest(BaseModel):
    email: str
    password: str

class UserCreate(BaseModel):
    email: str
    password: str
    full_name: Optional[str] = None
    role: str = "avocat"
    barreau: Optional[str] = None
    specialites: Optional[List[str]] = []

class UserUpdate(BaseModel):
    is_active: Optional[bool] = None
    lead_limit: Optional[int] = None
    subscription_status: Optional[str] = None
    role: Optional[str] = None


# Prospects
class ProspectCreate(BaseModel):
    # Noms FR (frontend)
    raison_sociale: Optional[str] = None
    ville: Optional[str] = None
    code_postal: Optional[str] = None
    code_naf: Optional[str] = None
    adresse: Optional[str] = None
    secteur_activite: Optional[str] = None
    statut: Optional[str] = None
    priorite: Optional[str] = None
    effectif: Optional[str] = None
    # Noms EN (retrocompat scraper)
    company_name: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    naf_code: Optional[str] = None
    naf_label: Optional[str] = None
    address: Optional[str] = None
    effectif_tranche: Optional[str] = None
    # Champs communs
    siren: Optional[str] = None
    siret: Optional[str] = None
    contact_name: Optional[str] = None
    contact_role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    country: str = "France"
    forme_juridique: Optional[str] = None
    date_creation: Optional[date] = None
    capital_social: Optional[int] = None
    chiffre_affaires: Optional[float] = None
    bodacc_procedure: Optional[str] = None
    is_international: bool = False
    is_multi_site: bool = False
    has_litigation_history: bool = False
    notes: Optional[str] = None
    source: str = "manuel"
    tags: Optional[List[str]] = []
    assigned_to: Optional[str] = None
    score: Optional[int] = None
    score_breakdown: Optional[Any] = None

class ProspectUpdate(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    statut: Optional[str] = None
    priorite: Optional[str] = None
    notes: Optional[str] = None
    assigned_to: Optional[str] = None
    has_formal_refusal: Optional[bool] = None
    consent_obtained: Optional[bool] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    raison_sociale: Optional[str] = None
    company_name: Optional[str] = None
    ville: Optional[str] = None
    city: Optional[str] = None
    score: Optional[int] = None
    score_breakdown: Optional[Any] = None

class ProspectStatusUpdate(BaseModel):
    status: str


# Clients
class ClientCreate(BaseModel):
    client_type: str = "personne_morale"
    raison_sociale: Optional[str] = None
    company_name: Optional[str] = None
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    siren: Optional[str] = None
    siret: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    adresse: Optional[str] = None
    city: Optional[str] = None
    ville: Optional[str] = None
    code_postal: Optional[str] = None
    postal_code: Optional[str] = None
    statut: Optional[str] = None
    status: str = "actif"
    since_date: Optional[date] = None
    is_confidential: bool = False
    notes: Optional[str] = None
    prospect_id: Optional[str] = None

class ClientUpdate(BaseModel):
    status: Optional[str] = None
    statut: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    is_confidential: Optional[bool] = None
    end_date: Optional[date] = None


# Dossiers
class DossierCreate(BaseModel):
    client_id: str
    reference: Optional[str] = None
    type_dossier: Optional[str] = None
    matiere: Optional[str] = None
    juridiction: Optional[str] = None
    partie_adverse_name: Optional[str] = None
    partie_adverse_siret: Optional[str] = None
    description: Optional[str] = None
    date_ouverture: Optional[date] = None

class DossierUpdate(BaseModel):
    status: Optional[str] = None
    date_cloture: Optional[date] = None
    description: Optional[str] = None
    juridiction: Optional[str] = None


# Conflits
class ConflictCheckRequest(BaseModel):
    entity_name: str
    siren: Optional[str] = None
    siret: Optional[str] = None
    entity_type: str = "prospect"

class ConflictDecision(BaseModel):
    check_id: str
    decision: str
    notes: Optional[str] = None


# Scraper
class SireneSearchRequest(BaseModel):
    q: str
    postal_code: Optional[str] = None
    city: Optional[str] = None
    naf_code: Optional[str] = None

class BodaccSearchRequest(BaseModel):
    siren: str
