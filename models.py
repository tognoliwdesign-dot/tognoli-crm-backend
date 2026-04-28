from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum

class LeadStatus(str, Enum):
    new = "new"
    contacted = "contacted"
    qualified = "qualified"
    proposal = "proposal"
    won = "won"
    lost = "lost"

class UserRole(str, Enum):
    admin = "admin"
    client = "client"

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    company_name: Optional[str] = ""
    role: UserRole = UserRole.client
    lead_limit: int = 100

class UserUpdate(BaseModel):
    company_name: Optional[str] = None
    is_active: Optional[bool] = None
    lead_limit: Optional[int] = None
    subscription_status: Optional[str] = None

class LeadCreate(BaseModel):
    company_name: str
    contact_name: Optional[str] = ""
    email: Optional[str] = ""
    phone: Optional[str] = ""
    website: Optional[str] = ""
    sector: Optional[str] = ""
    city: Optional[str] = ""
    country: Optional[str] = "France"
    notes: Optional[str] = ""
    linkedin_url: Optional[str] = ""
    source: Optional[str] = "manual"

class LeadUpdate(BaseModel):
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    sector: Optional[str] = None
    city: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[LeadStatus] = None
    score: Optional[int] = None
    linkedin_url: Optional[str] = None

class LeadStatusUpdate(BaseModel):
    status: LeadStatus

class AIMessageRequest(BaseModel):
    lead_id: str
    message_type: str = "cold_email"
    tone: Optional[str] = "professionnel"
    language: Optional[str] = "fr"

class AIScoreRequest(BaseModel):
    lead_id: str

class AIFollowupRequest(BaseModel):
    lead_id: str
    days_since_contact: int = 7

class EmailSendRequest(BaseModel):
    lead_id: str
    subject: str
    body: str
    recipient_email: str

class EmailConfigUpdate(BaseModel):
    daily_limit: Optional[int] = None
    min_delay_seconds: Optional[int] = None
    max_delay_seconds: Optional[int] = None

class ScraperRequest(BaseModel):
    sector: str
    city: str
    country: Optional[str] = "France"
    max_results: Optional[int] = 20

class CheckoutRequest(BaseModel):
    plan: str
    success_url: str
    cancel_url: str
