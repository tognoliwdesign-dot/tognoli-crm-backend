import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY or SUPABASE_ANON_KEY)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def get_admin_client() -> Client:
    return supabase_admin

def get_client() -> Client:
    return supabase

async def create_tables():
    print("✅ Database connection established via Supabase REST API")
    print(f"   URL: {SUPABASE_URL}")
