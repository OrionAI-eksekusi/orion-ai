"""
APEX Production Database Schema
PostgreSQL tables untuk multi-tenant SaaS
"""
import os

DATABASE_URL = os.getenv("DATABASE_URL")

async def init_apex_schema():
    """Initialize all APEX tables — idempotent, safe to run multiple times"""
    from app.services.database_service import get_connection
    conn, _ = get_connection()
    c = conn.cursor()
    
    try:
        # Users table
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                name TEXT,
                email TEXT UNIQUE,
                photo TEXT,
                plan TEXT DEFAULT 'trial',
                business_name TEXT,
                business_type TEXT,
                business_context TEXT,
                trial_end_date TIMESTAMPTZ DEFAULT NOW() + INTERVAL '3 days',
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Gmail tokens
        c.execute("""
            CREATE TABLE IF NOT EXISTS user_gmail_tokens (
                user_id TEXT PRIMARY KEY REFERENCES users(user_id),
                access_token TEXT,
                refresh_token TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # WA Messages
        c.execute("""
            CREATE TABLE IF NOT EXISTS wa_messages (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                phone TEXT,
                message TEXT,
                reply TEXT,
                intent TEXT,
                sentiment_score FLOAT DEFAULT 0.5,
                received_at TIMESTAMPTZ DEFAULT NOW(),
                received_timestamp TEXT,
                replied INTEGER DEFAULT 0,
                follow_up_sent INTEGER DEFAULT 0,
                follow_up_count INTEGER DEFAULT 0
            )
        """)

        # Leads CRM
        c.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                phone TEXT,
                name TEXT,
                email TEXT,
                current_state TEXT DEFAULT 'NEW_LEAD',
                lead_score INTEGER DEFAULT 0,
                last_contact TIMESTAMPTZ,
                follow_up_count INTEGER DEFAULT 0,
                notes TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, phone)
            )
        """)

        # Customer memories
        c.execute("""
            CREATE TABLE IF NOT EXISTS customer_memories (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                phone TEXT,
                memory_key TEXT,
                memory_value TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, phone, memory_key)
            )
        """)

        # Workspace SOP
        c.execute("""
            CREATE TABLE IF NOT EXISTS workspace_sop (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                sop_type TEXT,
                content TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(user_id, sop_type)
            )
        """)

        # Calendar events
        c.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                title TEXT,
                description TEXT,
                start_time TIMESTAMPTZ,
                end_time TIMESTAMPTZ,
                event_type TEXT DEFAULT 'meeting',
                status TEXT DEFAULT 'scheduled',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Tasks
        c.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                title TEXT,
                description TEXT,
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'pending',
                source TEXT,
                deadline TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Follow ups
        c.execute("""
            CREATE TABLE IF NOT EXISTS followups (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                phone TEXT,
                message TEXT,
                due_date TIMESTAMPTZ,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Billing usage
        c.execute("""
            CREATE TABLE IF NOT EXISTS billing_usages (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                usage_type TEXT,
                tokens_used INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Audit logs
        c.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                action TEXT,
                entity TEXT,
                entity_id TEXT,
                old_value JSONB,
                new_value JSONB,
                ip_address TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        # Invoices/Zenith
        c.execute("""
            CREATE TABLE IF NOT EXISTS invoices (
                id SERIAL PRIMARY KEY,
                user_id TEXT,
                vendor_name TEXT,
                item_name TEXT,
                vendor_price FLOAT,
                market_price FLOAT,
                markup_percentage FLOAT,
                risk_level TEXT DEFAULT 'SAFE',
                risk_score INTEGER DEFAULT 0,
                recommendation TEXT,
                potential_savings FLOAT DEFAULT 0,
                source TEXT DEFAULT 'manual',
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        print("[SCHEMA] ✅ All APEX tables initialized!")

    except Exception as e:
        print(f"[SCHEMA] ❌ Error: {e}")
        raise e
    finally:
        conn.commit()
        conn.close()