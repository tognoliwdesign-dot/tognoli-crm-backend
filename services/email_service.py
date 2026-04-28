import os
import asyncio
import random
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date
from database import get_admin_client
from dotenv import load_dotenv

load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
GLOBAL_DAILY_LIMIT = 50

async def get_email_config(user_id: str) -> dict:
    db = get_admin_client()
    result = db.table("email_config").select("*").eq("user_id", user_id).single().execute()
    if not result.data:
        config = {"user_id": user_id, "daily_limit": 10, "current_warmup_day": 1, "emails_sent_today": 0, "last_reset_date": date.today().isoformat(), "min_delay_seconds": 30, "max_delay_seconds": 90}
        db.table("email_config").insert(config).execute()
        return config
    return result.data

async def check_and_reset_daily_count(user_id: str, config: dict) -> dict:
    db = get_admin_client()
    today = date.today().isoformat()
    if config.get("last_reset_date", "") != today:
        new_day = min(config.get("current_warmup_day", 1) + 1, 30)
        new_limit = min(10 * new_day, GLOBAL_DAILY_LIMIT)
        updates = {"emails_sent_today": 0, "last_reset_date": today, "current_warmup_day": new_day, "daily_limit": new_limit}
        db.table("email_config").update(updates).eq("user_id", user_id).execute()
        config.update(updates)
    return config

async def send_email(user_id: str, lead_id: str, recipient_email: str, subject: str, body: str, html_body: str = None) -> dict:
    db = get_admin_client()
    config = await get_email_config(user_id)
    config = await check_and_reset_daily_count(user_id, config)
    daily_limit = config.get("daily_limit", 10)
    sent_today = config.get("emails_sent_today", 0)
    if sent_today >= daily_limit:
        return {"success": False, "error": f"Limite quotidienne atteinte ({daily_limit} emails/jour). Warmup actif."}
    log_result = db.table("email_logs").insert({"user_id": user_id, "lead_id": lead_id, "recipient_email": recipient_email, "subject": subject, "body": body, "status": "pending", "created_at": datetime.utcnow().isoformat()}).execute()
    log_id = log_result.data[0]["id"] if log_result.data else None
    min_delay = config.get("min_delay_seconds", 30)
    max_delay = config.get("max_delay_seconds", 90)
    delay = random.randint(min_delay, max_delay)
    try:
        await asyncio.sleep(delay)
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = recipient_email
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))
        await aiosmtplib.send(msg, hostname=SMTP_HOST, port=SMTP_PORT, start_tls=True, username=SMTP_USER, password=SMTP_PASSWORD)
        now = datetime.utcnow().isoformat()
        if log_id:
            db.table("email_logs").update({"status": "sent", "sent_at": now}).eq("id", log_id).execute()
        db.table("email_config").update({"emails_sent_today": sent_today + 1}).eq("user_id", user_id).execute()
        db.table("leads").update({"status": "contacted", "updated_at": now}).eq("id", lead_id).execute()
        return {"success": True, "delay_used": delay, "emails_remaining_today": daily_limit - sent_today - 1}
    except Exception as e:
        if log_id:
            db.table("email_logs").update({"status": "failed"}).eq("id", log_id).execute()
        return {"success": False, "error": str(e)}
