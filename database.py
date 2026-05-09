"""LEXARYS - Base de donnees Supabase"""
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
        role TEXT DEFAULT 'avocat',
        barreau TEXT,
        specialites TEXT[] DEFAULT '{}',
        is_active BOOLEAN DEFAULT TRUE,
        lead_limit INTEGER DEFAULT 500,
        subscription_status TEXT DEFAULT 'trial',
        features_enabled JSONB DEFAULT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS prospects (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID REFERENCES users(id),
        assigned_to UUID REFERENCES users(id),
        raison_sociale TEXT,
        siren TEXT,
        siret TEXT,
        contact_name TEXT,
        contact_role TEXT,
        email TEXT,
        phone TEXT,
        website TEXT,
        adresse TEXT,
        ville TEXT,
        code_postal TEXT,
        country TEXT DEFAULT 'France',
        code_naf TEXT,
        secteur_activite TEXT,
        effectif TEXT,
        chiffre_affaires NUMERIC,
        forme_juridique TEXT,
        date_creation DATE,
        capital_social BIGINT,
        bodacc_procedure TEXT,
        is_international BOOLEAN DEFAULT FALSE,
        is_multi_site BOOLEAN DEFAULT FALSE,
        has_litigation_history BOOLEAN DEFAULT FALSE,
        status TEXT DEFAULT 'identifie',
        priority TEXT DEFAULT 'normal',
        score INTEGER DEFAULT 0,
        score_breakdown JSONB DEFAULT '{}',
        score_updated_at TIMESTAMPTZ,
        nb_contacts INTEGER DEFAULT 0,
        last_contact_at TIMESTAMPTZ,
        has_formal_refusal BOOLEAN DEFAULT FALSE,
        consent_obtained BOOLEAN DEFAULT FALSE,
        consent_date TIMESTAMPTZ,
        notes TEXT,
        source TEXT DEFAULT 'manuel',
        tags TEXT[] DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS clients (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id UUID REFERENCES users(id),
        client_type TEXT DEFAULT 'personne_morale',
        raison_sociale TEXT,
        last_name TEXT,
        first_name TEXT,
        siren TEXT,
        siret TEXT,
        email TEXT,
        phone TEXT,
        adresse TEXT,
        ville TEXT,
        code_postal TEXT,
        status TEXT DEFAULT 'actif',
        since_date DATE,
        end_date DATE,
        is_confidential BOOLEAN DEFAULT FALSE,
        notes TEXT,
        prospect_id UUID REFERENCES prospects(id),
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS dossiers (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        reference TEXT UNIQUE,
        client_id UUID REFERENCES clients(id),
        avocat_id UUID REFERENCES users(id),
        type_dossier TEXT,
        matiere TEXT,
        juridiction TEXT,
        partie_adverse_name TEXT,
        partie_adverse_siret TEXT,
        status TEXT DEFAULT 'ouvert',
        date_ouverture DATE DEFAULT CURRENT_DATE,
        date_cloture DATE,
        conflict_check_done BOOLEAN DEFAULT FALSE,
        conflict_check_date TIMESTAMPTZ,
        conflict_check_result TEXT,
        description TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS conflict_checks (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        checked_by UUID REFERENCES users(id),
        checked_entity_name TEXT NOT NULL,
        checked_entity_siren TEXT,
        checked_entity_siret TEXT,
        checked_entity_type TEXT DEFAULT 'prospect',
        result TEXT NOT NULL,
        conflicts_found JSONB DEFAULT '[]',
        decision TEXT,
        decision_notes TEXT,
        decision_at TIMESTAMPTZ,
        checked_at TIMESTAMPTZ DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS prospect_contacts (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        prospect_id UUID REFERENCES prospects(id) ON DELETE CASCADE,
        user_id UUID REFERENCES users(id),
        contact_type TEXT NOT NULL,
        contact_date TIMESTAMPTZ DEFAULT NOW(),
        notes TEXT,
        response TEXT
    );
    """
    try:
        supabase.rpc("exec_sql", {"query": sql}).execute()
    except Exception:
        pass

    # Migration : ajouter features_enabled si colonne absente
    migration = "ALTER TABLE users ADD COLUMN IF NOT EXISTS features_enabled JSONB DEFAULT NULL;"
    try:
        supabase.rpc("exec_sql", {"query": migration}).execute()
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
                "lead_limit": 9999,
                "subscription_status": "active",
            }).execute()
            print(f"Admin cree : {admin_email}")
    except Exception as e:
        print(f"Admin init: {e}")
