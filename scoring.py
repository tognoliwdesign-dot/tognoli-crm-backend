"""LEXARYS - Algorithme de scoring (100% algorithmique, sans IA)"""
from dataclasses import dataclass
from typing import Optional
from datetime import date

HIGH_RISK_NAF = {"64","65","66","68","70","69","71","72","86","87","88","84","85","41","42","43","62","63"}
MEDIUM_RISK_NAF = {"46","47","10","11","12","13","14","15","16","17","18","19","20","21","22","23","24","25","26","27","28","29","30","49","50","51","52","53","55","56","61","77","78","79","80","81","82"}
EFFECTIF_SCORES = {"NN":0,"00":1,"01":3,"02":5,"03":7,"11":9,"12":12,"21":15,"22":18,"31":20,"32":20,"41":20,"42":20,"51":20,"52":20,"53":20}
HIGH_VALUE_LEGAL_FORMS = {"5505","5510","5710","5720","5498","5310","6540","6532"}

@dataclass
class ProspectData:
    company_name: str
    naf_code: Optional[str] = None
    effectif_tranche: Optional[str] = None
    forme_juridique: Optional[str] = None
    date_creation: Optional[date] = None
    capital_social: Optional[int] = None
    bodacc_procedure: Optional[str] = None
    nb_contacts: int = 0
    has_formal_refusal: bool = False
    has_consent: bool = False
    is_international: bool = False
    is_multi_site: bool = False
    has_litigation_history: bool = False

@dataclass
class ScoreResult:
    total: int
    level: str
    level_color: str
    breakdown: dict
    deonto_alert: bool
    deonto_reason: str

def score_prospect(data: ProspectData) -> ScoreResult:
    breakdown = {}
    total = 0
    deonto_alert = False
    deonto_reason = ""
    if data.has_formal_refusal:
        return ScoreResult(total=0,level="bloque",level_color="black",breakdown={"deontologie":"BLOQUE - Refus explicite"},deonto_alert=True,deonto_reason="Refus explicite. Toute approche est interdite (RIN Art. 161).")
    if data.nb_contacts >= 3 and not data.has_consent:
        deonto_alert = True
        deonto_reason = f"{data.nb_contacts} contacts sans consentement. Vérifiez la conformité déontologique."
    pts = EFFECTIF_SCORES.get(data.effectif_tranche or "", 3)
    breakdown["taille_effectif"] = {"pts": pts, "max": 20, "detail": f"Tranche: {data.effectif_tranche or 'inconnue'}"}
    total += pts
    naf_prefix = (data.naf_code or "")[:2]
    if naf_prefix in HIGH_RISK_NAF: pts, detail = 20, f"Secteur haut risque juridique (NAF: {data.naf_code})"
    elif naf_prefix in MEDIUM_RISK_NAF: pts, detail = 12, f"Secteur risque moyen (NAF: {data.naf_code})"
    else: pts, detail = 5, f"Secteur faible exposition (NAF: {data.naf_code or 'inconnu'})"
    breakdown["secteur_naf"] = {"pts": pts, "max": 20, "detail": detail}
    total += pts
    if data.date_creation:
        today = date.today()
        age = (today - data.date_creation).days / 365.25
        pts = 10 if age>=10 else (8 if age>=5 else (5 if age>=3 else (3 if age>=1 else 1)))
        detail = f"Entreprise de {age:.1f} ans"
    else: pts, detail = 3, "Date création inconnue"
    breakdown["anciennete"] = {"pts": pts, "max": 10, "detail": detail}
    total += pts
    if data.forme_juridique in HIGH_VALUE_LEGAL_FORMS: pts, detail = 10, f"Forme juridique forte (code: {data.forme_juridique})"
    elif data.forme_juridique: pts, detail = 5, f"Forme standard ({data.forme_juridique})"
    else: pts, detail = 3, "Forme inconnue"
    breakdown["forme_juridique"] = {"pts": pts, "max": 10, "detail": detail}
    total += pts
    if data.capital_social:
        pts = 10 if data.capital_social>=1_000_000 else (8 if data.capital_social>=100_000 else (5 if data.capital_social>=10_000 else (3 if data.capital_social>=1_000 else 1)))
        detail = f"Capital: {data.capital_social:,}EUR"
    else: pts, detail = 2, "Capital inconnu"
    breakdown["capital_social"] = {"pts": pts, "max": 10, "detail": detail}
    total += pts
    proc = data.bodacc_procedure
    if proc=="sauvegarde": pts,detail=15,"Procédure sauvegarde - besoin urgent avocat"
    elif proc=="redressement": pts,detail=12,"Redressement judiciaire"
    elif proc=="cession": pts,detail=10,"Cession d'activité"
    elif proc=="liquidation": pts,detail=0,"Liquidation - risque non-recouvrement"
    else: pts,detail=8,"Aucune procédure (situation saine)"
    breakdown["bodacc"] = {"pts": pts, "max": 15, "detail": detail}
    total += pts
    pts = 5 if data.is_international else (3 if data.is_multi_site else 1)
    breakdown["implantation"] = {"pts": pts, "max": 5, "detail": "International" if data.is_international else ("Multi-sites" if data.is_multi_site else "Mono-site")}
    total += pts
    pts = 10 if data.has_litigation_history else 3
    breakdown["contentieux"] = {"pts": pts, "max": 10, "detail": "Contentieux identifié" if data.has_litigation_history else "Aucun contentieux public"}
    total += pts
    penalty = 0
    if data.nb_contacts >= 4:
        penalty = 15; deonto_alert = True
        deonto_reason = f"ALERTE: {data.nb_contacts} contacts. Risque harcèlement (RIN Art. 161)."
    elif data.nb_contacts >= 2 and not data.has_consent:
        penalty = 5
        if not deonto_alert: deonto_alert = True; deonto_reason = f"{data.nb_contacts} contacts sans consentement."
    if penalty > 0:
        breakdown["penalite_deonto"] = {"pts": -penalty, "max": 0, "detail": f"Pénalité déontologique: -{penalty}pts"}
        total -= penalty
    total = max(0, min(100, total))
    if total >= 75: level,color = "prioritaire","red"
    elif total >= 50: level,color = "fort","orange"
    elif total >= 25: level,color = "moyen","yellow"
    else: level,color = "faible","gray"
    return ScoreResult(total=total,level=level,level_color=color,breakdown=breakdown,deonto_alert=deonto_alert,deonto_reason=deonto_reason)

def score_to_dict(result: ScoreResult) -> dict:
    return {"total": result.total, "level": result.level, "level_color": result.level_color, "breakdown": result.breakdown, "deonto_alert": result.deonto_alert, "deonto_reason": result.deonto_reason}
