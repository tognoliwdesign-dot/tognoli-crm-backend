"""LEXARYS — Base de données Supabase"""
import os
from supabase import create_client, Client

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_ANON_KEY", ""))

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

async def create_tables():
    sql = """
    CREATE TABLE IF NOT EXISTS users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT,
        first_name TEXT,
        last_name TEXT,
        role TEXT DEFAULT 'avocat',
        barreau TEXT,
        specialites TEXT[] DEFAULT '{}',
        is_active BOOLEAN DEFAULT TRUE,
        lead_limit INTEGER DEFAULT 500,
        subscription_status TEXT DEFAULT 'trial',
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS prospects (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID REFERENCES users(id),
        company_name TEXT NOT NULL,
        siren TEXT, siret TEXT,
        contact_name TEXT, email TEXT, phone TEXT,
        city TEXT, postal_code TEXT, country TEXT DEFAULT 'France',
        naf_code TEXT, naf_label TEXT,
        effectif_tranche TEXT, forme_juridique TEXT,
        date_creation DATE, capital_social BIGINT,
        bodacc_procedure TEXT,
        is_international BOOLEAN DEFAULT FALSE,
        is_multi_site BOOLEAN DEFAULT FALSE,
        has_litigation_history BOOLEAN DEFAULT FALSE,
        status TEXT DEFAULT 'nouveau',
        score INTEGER DEFAULT 0,
        score_breakdown JSONB DEFAULT '{}',
        score_updated_at TIMESTAMPTZ,
        nb_contacts INTEGER DEFAULT 0,
        last_contact_at TIMESTAMPTZ,
        has_formal_refusal BOOLEAN DEFAULT FALSE,
        consent_obtained BOOLEAN DEFAULT FALSE,
        deonto_alert BOOLEAN DEFAULT FALSE,
        notes TEXT, source TEXT DEFAULT 'manuel',
        tags TEXT[] DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS clients (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID REFERENCES users(id),
        client_type TEXT DEFAULT 'personne_morale',
        company_name TEXT, last_name TEXT, first_name TEXT,
        siren TEXT, siret TEXT,
        email TEXT, phone TEXT, address TEXT,
        city TEXT, postal_code TEXT,
        status TEXT DEFAULT 'actif',
        since_date DATE, end_date DATE,
        is_confidential BOOLEAN DEFAULT FALSE,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS dossiers (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        reference TEXT UNIQUE,
        client_id UUID REFERENCES clients(id),
        avocat_id UUID REFERENCES users(id),
        titre TEXT,
        type_dossier TEXT, matiere TEXT, juridiction TEXT,
        partie_adverse TEXT, partie_adverse_siren TEXT,
        status TEXT DEFAULT 'ouvert',
        date_ouverture DATE DEFAULT CURRENT_DATE,
        date_cloture DATE,
        conflict_check_done BOOLEAN DEFAULT FALSE,
        conflict_check_date TIMESTAMPTZ,
        conflict_check_result TEXT,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS conflict_checks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        checked_by UUID REFERENCES users(id),
        entity_name TEXT NOT NULL,
        siren TEXT, siret TEXT,
        entity_type TEXT DEFAULT 'prospect',
        result TEXT NOT NULL,
        matches JSONB DEFAULT '[]',
        recommendation TEXT,
        decision TEXT,
        decision_notes TEXT,
        decision_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS prospect_contacts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        prospect_id UUID REFERENCES prospects(id) ON DELETE CASCADE,
        user_id UUID REFERENCES users(id),
        contact_mode TEXT NOT NULL,
        contact_date TIMESTAMPTZ DEFAULT NOW(),
        notes TEXT
    );
    """
    try:
        supabase.rpc("exec_sql", {"query": sql}).execute()
    except Exception:
        pass

async def create_admin_if_missing():
    import os
    from passlib.context import CryptContext
    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
    admin_email = os.getenv("ADMIN_EMAIL", "admin@lexarys.fr")
    admin_password = os.getenv("ADMIN_PASSWORD", "Lexarys2024!")
    try:
        existing = supabase.table("users").select("id").eq("email", admin_email).execute()
        if not existing.data:
            supabase.table("users").insert({
                "email": admin_email,
                "password_hash": pwd_ctx.hash(admin_password),
                "full_name": "Administrateur",
                "role": "admin",
                "is_active": True,
            }).execute()
            print(f"Admin créé : {admin_email}")
    except Exception as e:
        print(f"Admin init: {e}")
