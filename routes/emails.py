"""LEXARYS - Routes Emails (templates, SMTP settings, envoi, verif)"""
from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from database import supabase
from auth import get_current_user
from pydantic import BaseModel
from typing import Optional
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr

router = APIRouter(prefix="/emails", tags=["emails"])


class TemplateBody(BaseModel):
    nom: str
    sujet: Optional[str] = ""
    corps: Optional[str] = ""
    actif: Optional[bool] = True


class SettingsBody(BaseModel):
    smtp_email: Optional[str] = None
    smtp_app_password: Optional[str] = None
    smtp_signature: Optional[str] = None
    smtp_host: Optional[str] = "smtp.gmail.com"
    smtp_port: Optional[int] = 587
    smtp_provider: Optional[str] = "gmail"


class SendEmailBody(BaseModel):
    template_id: Optional[str] = None
    sujet: Optional[str] = None
    corps: Optional[str] = None
    to: Optional[str] = None  # override l'email cible si specifie


# ============================================================
# TEMPLATES — CRUD
# ============================================================

@router.get("/templates")
async def list_templates(user=Depends(get_current_user)):
    try:
        r = supabase.table("email_templates").select("*").eq("user_id", user["id"]).order("modifie_le", desc=True).execute()
        return r.data or []
    except Exception as e:
        raise HTTPException(500, f"Erreur lecture templates: {str(e)}")


@router.post("/templates")
async def create_template(body: TemplateBody, user=Depends(get_current_user)):
    try:
        payload = {
            "user_id": user["id"],
            "nom": body.nom.strip(),
            "sujet": (body.sujet or "").strip(),
            "corps": body.corps or "",
            "actif": body.actif if body.actif is not None else True,
        }
        r = supabase.table("email_templates").insert(payload).execute()
        return (r.data or [{}])[0]
    except Exception as e:
        raise HTTPException(500, f"Erreur creation template: {str(e)}")


@router.put("/templates/{template_id}")
async def update_template(template_id: str, body: TemplateBody, user=Depends(get_current_user)):
    try:
        payload = {
            "nom": body.nom.strip(),
            "sujet": (body.sujet or "").strip(),
            "corps": body.corps or "",
            "actif": body.actif if body.actif is not None else True,
            "modifie_le": datetime.now(timezone.utc).isoformat(),
        }
        supabase.table("email_templates").update(payload).eq("id", template_id).eq("user_id", user["id"]).execute()
        return {"status": "updated", "id": template_id}
    except Exception as e:
        raise HTTPException(500, f"Erreur mise a jour template: {str(e)}")


@router.delete("/templates/{template_id}")
async def delete_template(template_id: str, user=Depends(get_current_user)):
    try:
        supabase.table("email_templates").delete().eq("id", template_id).eq("user_id", user["id"]).execute()
        return {"status": "deleted", "id": template_id}
    except Exception as e:
        raise HTTPException(500, f"Erreur suppression: {str(e)}")


# ============================================================
# SETTINGS SMTP — par utilisateur
# ============================================================

@router.get("/settings")
async def get_settings(user=Depends(get_current_user)):
    try:
        r = supabase.table("user_email_settings").select("*").eq("user_id", user["id"]).execute()
        if r.data:
            d = r.data[0]
            # Ne pas renvoyer le password en clair, juste indiquer s'il est defini
            d["has_password"] = bool(d.get("smtp_app_password"))
            d["smtp_app_password"] = None  # masque
            return d
        return {"user_id": user["id"], "has_password": False, "smtp_provider": "gmail", "smtp_host": "smtp.gmail.com", "smtp_port": 587}
    except Exception as e:
        raise HTTPException(500, f"Erreur settings: {str(e)}")


@router.put("/settings")
async def update_settings(body: SettingsBody, user=Depends(get_current_user)):
    try:
        existing = supabase.table("user_email_settings").select("user_id").eq("user_id", user["id"]).execute()
        payload = {
            "user_id": user["id"],
            "smtp_email": body.smtp_email,
            "smtp_signature": body.smtp_signature or "",
            "smtp_host": body.smtp_host or "smtp.gmail.com",
            "smtp_port": body.smtp_port or 587,
            "smtp_provider": body.smtp_provider or "gmail",
            "modifie_le": datetime.now(timezone.utc).isoformat(),
        }
        # Update password uniquement si fourni (non-vide)
        if body.smtp_app_password:
            payload["smtp_app_password"] = body.smtp_app_password.replace(" ", "")  # Gmail app password sans espaces
        if existing.data:
            supabase.table("user_email_settings").update(payload).eq("user_id", user["id"]).execute()
        else:
            if not body.smtp_app_password:
                # Insertion premiere fois sans password — autoriser mais avertir
                payload["smtp_app_password"] = ""
            supabase.table("user_email_settings").insert(payload).execute()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(500, f"Erreur enregistrement: {str(e)}")


# ============================================================
# VERIFICATION email prospect (avocat coche manuellement)
# ============================================================

class VerifyBody(BaseModel):
    verified: bool


@router.put("/prospects/{prospect_id}/verify")
async def verify_email(prospect_id: str, body: VerifyBody, user=Depends(get_current_user)):
    try:
        payload = {
            "email_verified": body.verified,
            "email_verified_at": datetime.now(timezone.utc).isoformat() if body.verified else None,
            "email_verified_by": user["id"] if body.verified else None,
        }
        supabase.table("prospects").update(payload).eq("id", prospect_id).eq("user_id", user["id"]).execute()
        return {"status": "ok", "verified": body.verified}
    except Exception as e:
        raise HTTPException(500, f"Erreur verification: {str(e)}")


# ============================================================
# ENVOI EMAIL
# ============================================================

def _substitute_placeholders(text: str, prospect: dict) -> str:
    """Remplace les placeholders {nom_entreprise}, {ville}, etc. par les valeurs du prospect."""
    if not text:
        return ""
    mapping = {
        "{nom_entreprise}": (prospect.get("raison_sociale") or "").strip(),
        "{raison_sociale}": (prospect.get("raison_sociale") or "").strip(),
        "{company_name}": (prospect.get("raison_sociale") or "").strip(),
        "{ville}": (prospect.get("ville") or "").strip(),
        "{city}": (prospect.get("ville") or "").strip(),
        "{code_postal}": (prospect.get("code_postal") or "").strip(),
        "{adresse}": (prospect.get("adresse") or "").strip(),
        "{siren}": (prospect.get("siren") or "").strip(),
        "{contact_nom}": (prospect.get("contact_nom") or prospect.get("contact_name") or "").strip(),
        "{contact_prenom}": (prospect.get("contact_prenom") or "").strip(),
        "{secteur}": (prospect.get("secteur_activite") or "").strip(),
        "{score_lexarys}": str(int(prospect.get("lexarys_score") or 0)) if prospect.get("lexarys_score") else "—",
    }
    out = text
    for k, v in mapping.items():
        out = out.replace(k, v)
    return out


@router.post("/prospects/{prospect_id}/send")
async def send_email_to_prospect(prospect_id: str, body: SendEmailBody, user=Depends(get_current_user)):
    """Envoie un email au prospect en utilisant le SMTP configure de l'avocat."""
    try:
        # 1) Recuperer le prospect
        p = supabase.table("prospects").select("*").eq("id", prospect_id).eq("user_id", user["id"]).single().execute()
        if not p.data:
            raise HTTPException(404, "Prospect introuvable")
        prospect = p.data

        # 2) Verification obligatoire de l'email (deontologie)
        if not prospect.get("email_verified"):
            raise HTTPException(400, "Email non verifie. L'avocat doit cocher 'email verifie' pour se dedoiner.")

        # 3) Adresse cible
        to_addr = body.to or prospect.get("email_scrape") or prospect.get("email")
        if not to_addr or "@" not in to_addr:
            raise HTTPException(400, "Aucune adresse email valide pour ce prospect")

        # 4) Recuperer le template OU utiliser les champs fournis
        sujet = body.sujet or ""
        corps = body.corps or ""
        if body.template_id:
            tpl = supabase.table("email_templates").select("*").eq("id", body.template_id).eq("user_id", user["id"]).single().execute()
            if tpl.data:
                sujet = tpl.data.get("sujet") or sujet
                corps = tpl.data.get("corps") or corps
        if not sujet or not corps:
            raise HTTPException(400, "Sujet ou corps de l'email manquant")

        # 5) Substituer les placeholders
        sujet = _substitute_placeholders(sujet, prospect)
        corps = _substitute_placeholders(corps, prospect)

        # 6) Recuperer SMTP settings
        s = supabase.table("user_email_settings").select("*").eq("user_id", user["id"]).single().execute()
        if not s.data:
            raise HTTPException(400, "SMTP non configure — renseignez vos parametres dans Templates -> SMTP")
        st = s.data
        if not st.get("smtp_email") or not st.get("smtp_app_password"):
            raise HTTPException(400, "SMTP incomplet — renseignez l'email et le mot de passe d'application")

        # 7) Ajout signature
        if st.get("smtp_signature"):
            corps = corps + "\n\n" + st["smtp_signature"]

        # 8) Envoi via smtplib
        msg = MIMEMultipart("alternative")
        msg["Subject"] = sujet
        msg["From"] = formataddr(("Lexarys CRM", st["smtp_email"]))
        msg["To"] = to_addr
        msg.attach(MIMEText(corps, "plain", "utf-8"))
        # version HTML basique (replace newlines by <br>)
        html_body = "<html><body><p>" + corps.replace("\n", "<br>") + "</p></body></html>"
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        host = st.get("smtp_host") or "smtp.gmail.com"
        port = st.get("smtp_port") or 587
        password = (st.get("smtp_app_password") or "").replace(" ", "")
        # Railway bloque souvent les ports 25/587/465 STARTTLS — on essaie plusieurs strategies
        sent_ok = False
        send_error = None
        # Strategy 1: SMTP_SSL port 465 (Railway-friendly)
        try:
            with smtplib.SMTP_SSL(host, 465, timeout=15) as server:
                server.login(st["smtp_email"], password)
                server.send_message(msg)
            sent_ok = True
        except smtplib.SMTPAuthenticationError as e:
            raise HTTPException(401, f"Identifiants SMTP refuses : verifier le mot de passe d'application Google (2FA requis). Detail: {str(e)[:120]}")
        except Exception as e:
            send_error = ("SSL_465", str(e))

        # Strategy 2: STARTTLS port 587 fallback
        if not sent_ok:
            try:
                with smtplib.SMTP(host, port or 587, timeout=15) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(st["smtp_email"], password)
                    server.send_message(msg)
                sent_ok = True
            except smtplib.SMTPAuthenticationError as e:
                raise HTTPException(401, f"Identifiants SMTP refuses (587). Verifier le mot de passe d'application Google. Detail: {str(e)[:120]}")
            except Exception as e:
                send_error = (send_error[0] if send_error else "STARTTLS_587", str(e))

        if not sent_ok:
            err_msg = "Reseau Railway bloque la connexion vers le serveur SMTP. "
            err_msg += "Solution conseillee : utiliser un relai SMTP HTTP comme Brevo (sendinblue) ou Resend a la place de Gmail direct. "
            err_msg += f"(Detail technique : {send_error[1][:120] if send_error else 'unknown'})"
            raise HTTPException(503, err_msg)

        # 9) Mettre a jour le prospect
        supabase.table("prospects").update({
            "email_sent_at": datetime.now(timezone.utc).isoformat(),
            "email_sent_count": (prospect.get("email_sent_count") or 0) + 1,
        }).eq("id", prospect_id).execute()

        return {"status": "sent", "to": to_addr, "sujet": sujet}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Erreur envoi email: {str(e)}")
