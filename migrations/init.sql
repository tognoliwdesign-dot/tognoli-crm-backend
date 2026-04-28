-- TOGNOLI CRM AI -- Migration initiale Supabase
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS users (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'client' CHECK (role IN ('admin', 'client')),
    company_name VARCHAR(255) DEFAULT '',
    is_active BOOLEAN DEFAULT true,
    lead_limit INTEGER DEFAULT 100,
    subscription_status VARCHAR(50) DEFAULT 'trial',
    stripe_customer_id VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS leads (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    company_name VARCHAR(255) NOT NULL,
    contact_name VARCHAR(255) DEFAULT '',
    email VARCHAR(255) DEFAULT '',
    phone VARCHAR(50) DEFAULT '',
    website VARCHAR(500) DEFAULT '',
    sector VARCHAR(100) DEFAULT '',
    city VARCHAR(100) DEFAULT '',
    country VARCHAR(100) DEFAULT 'France',
    status VARCHAR(50) DEFAULT 'new' CHECK (status IN ('new','contacted','qualified','proposal','won','lost')),
    score INTEGER DEFAULT 0 CHECK (score >= 0 AND score <= 100),
    notes TEXT DEFAULT '',
    linkedin_url VARCHAR(500) DEFAULT '',
    source VARCHAR(100) DEFAULT 'manual',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ai_actions (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    lead_id UUID REFERENCES leads(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    action_type VARCHAR(50) CHECK (action_type IN ('message','scoring','followup','analysis')),
    prompt TEXT DEFAULT '',
    result TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_logs (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    lead_id UUID REFERENCES leads(id) ON DELETE SET NULL,
    recipient_email VARCHAR(255) NOT NULL,
    subject VARCHAR(500) DEFAULT '',
    body TEXT DEFAULT '',
    status VARCHAR(50) DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','bounced')),
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS email_config (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id UUID UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    daily_limit INTEGER DEFAULT 10,
    current_warmup_day INTEGER DEFAULT 1,
    emails_sent_today INTEGER DEFAULT 0,
    last_reset_date DATE DEFAULT CURRENT_DATE,
    min_delay_seconds INTEGER DEFAULT 30,
    max_delay_seconds INTEGER DEFAULT 90,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    stripe_subscription_id VARCHAR(255) UNIQUE,
    stripe_customer_id VARCHAR(255),
    plan_name VARCHAR(50),
    status VARCHAR(50) DEFAULT 'active',
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_user_id ON leads(user_id);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_actions_lead_id ON ai_actions(lead_id);
CREATE INDEX IF NOT EXISTS idx_email_logs_user_id ON email_logs(user_id);

ALTER TABLE users DISABLE ROW LEVEL SECURITY;
ALTER TABLE leads DISABLE ROW LEVEL SECURITY;
ALTER TABLE ai_actions DISABLE ROW LEVEL SECURITY;
ALTER TABLE email_logs DISABLE ROW LEVEL SECURITY;
ALTER TABLE email_config DISABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions DISABLE ROW LEVEL SECURITY;
