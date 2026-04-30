"""LEXARYS — Modèles Pydantic"""
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import date, datetime

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str = "avocat"
    barreau: Optional[str] = None
    specialites: Optional[List[str]] = []

class UserUpdate(BaseModel):
    is_active: Optional[bool] = None
    role: Optional[str] = None

class ProspectCreate(BaseModel):
    company_name: str
    siren: Optional[str] = None
    siret: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "France"
    naf_code: Optional[str] = None
    naf_label: Optional[str] = None
    effectif_tranche: Optional[str] = None
    forme_juridique: Optional[str] = None
    date_creation: Optional[date] = None
    capital_social: Optional[int] = None
    bodacc_procedure: Optional[str] = None
    is_international: bool = False
    is_multi_site: bool = False
    has_litigation_history: bool = False
    notes: Optional[str] = None
    source: str = "manuel"
    tags: Optional[List[str]] = []
    assigned_to: Optional[str] = None

class ProspectUpdate(BaseModel):
    status: Optional[str] = None
    company_name: Optional[str] = None
    siren: Optional[str] = None
    siret: Optional[str] = None
    naf_code: Optional[str] = None
    naf_label: Optional[str] = None
    effectif_tranche: Optional[str] = None
    forme_juridique: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    has_formal_refusal: Optional[bool] = None
    consent_obtained: Optional[bool] = None

class ProspectStatusUpdate(BaseModel):
    status: str

class ClientCreate(BaseModel):
    client_type: str = "personne_morale"
    company_name: Optional[str] = None
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    siren: Optional[str] = None
    siret: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    status: str = "actif"
    since_date: Optional[date] = None
    is_confidential: bool = False
    notes: Optional[str] = None

class ClientUpdate(BaseModel):
    status: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None
    end_date: Optional[date] = None

class DossierCreate(BaseModel):
    client_id: Optional[str] = None
    reference: Optional[str] = None
    titre: Optional[str] = None
    type_dossier: Optional[str] = None
    matiere: Optional[str] = None
    juridiction: Optional[str] = None
    partie_adverse: Optional[str] = None
    partie_adverse_siren: Optional[str] = None
    status: str = "ouvert"
    date_ouverture: Optional[date] = None
    notes: Optional[str] = None

class DossierUpdate(BaseModel):
    status: Optional[str] = None
    titre: Optional[str] = None
    type_dossier: Optional[str] = None
    client_id: Optional[str] = None
    date_ouverture: Optional[date] = None
    date_cloture: Optional[date] = None
    juridiction: Optional[str] = None
    partie_adverse: Optional[str] = None
    partie_adverse_siren: Optional[str] = None
    notes: Optional[str] = None

class ConflictCheckRequest(BaseModel):
    entity_name: str
    siren: Optional[str] = None
    siret: Optional[str] = None
    entity_type: str = "prospect"
    prospect_id: Optional[str] = None
    dossier_id: Optional[str] = None

class ConflictDecision(BaseModel):
    check_id: str
    decision: str
    notes: Optional[str] = None

class SireneSearchRequest(BaseModel):
    q: str
    postal_code: Optional[str] = None

class BodaccSearchRequest(BaseModel):
    siren: str
