import os
import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from auth import get_current_user
from database import get_admin_client
from models import CheckoutRequest
from dotenv import load_dotenv

load_dotenv()
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
router = APIRouter()

PLANS = {
    "starter": {"price": 2900, "name": "Starter", "lead_limit": 200},
    "pro": {"price": 4900, "name": "Pro", "lead_limit": 500},
    "enterprise": {"price": 9900, "name": "Enterprise", "lead_limit": 2000},
}

@router.post("/create-checkout")
async def create_checkout(body: CheckoutRequest, current_user: dict = Depends(get_current_user)):
    if body.plan not in PLANS:
        raise HTTPException(status_code=400, detail="Plan invalide")
    plan = PLANS[body.plan]
    session = stripe.checkout.Session.create(payment_method_types=["card"], line_items=[{"price_data": {"currency": "eur", "product_data": {"name": f"TOGNOLI CRM - Plan {plan['name']}"}, "unit_amount": plan["price"], "recurring": {"interval": "month"}}, "quantity": 1}], mode="subscription", customer_email=current_user["email"], success_url=body.success_url + "?session_id={CHECKOUT_SESSION_ID}", cancel_url=body.cancel_url, metadata={"user_id": current_user["id"], "plan": body.plan})
    return {"checkout_url": session.url, "session_id": session.id}

@router.post("/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        if WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
        else:
            import json
            event = json.loads(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    db = get_admin_client()
    if event.get("type") == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = session.get("metadata", {}).get("user_id")
        plan = session.get("metadata", {}).get("plan", "starter")
        if user_id and plan in PLANS:
            plan_info = PLANS[plan]
            db.table("users").update({"subscription_status": "active", "lead_limit": plan_info["lead_limit"], "stripe_customer_id": session.get("customer")}).eq("id", user_id).execute()
            db.table("subscriptions").upsert({"user_id": user_id, "stripe_subscription_id": session.get("subscription"), "stripe_customer_id": session.get("customer"), "plan_name": plan, "status": "active"}).execute()
    return {"status": "ok"}

@router.get("/plans")
async def get_plans():
    return PLANS
