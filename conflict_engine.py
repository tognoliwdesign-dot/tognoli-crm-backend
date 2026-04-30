"""LEXARYS - Moteur conflits d'intérêts (Art. 4 RIN)"""
import re
from difflib import SequenceMatcher
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

LEGAL_SUFFIXES = [r'\bS\.?A\.?S\.?U?\b',r'\bS\.?A\.?\b',r'\bS\.?A\.?R\.?L\.?\b',r'\bS\.?N\.?C\.?\b',r'\bS\.?C\.?I\.?\b',r'\bE\.?U\.?R\.?L\.?\b',r'\bG\.?I\.?E\.?\b',r'\bCORPORATION\b',r'\bGROUP\b',r'\bGROUPE\b',r'\bHOLDING\b',r'\bFRANCE\b',r'\bINTERNATIONAL\b']

def normalize_name(name: str) -> str:
    if not name: return ""
    text = name.upper().strip()
    for pattern in LEGAL_SUFFIXES:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(LE|LA|LES|DE|DU|DES|ET|&|THE)\b', '', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def normalize_siren(siren: str) -> str:
    return re.sub(r'\D', '', siren or '')[:9]

def normalize_siret(siret: str) -> str:
    return re.sub(r'\D', '', siret or '')[:14]

def siren_from_siret(siret: str) -> str:
    clean = normalize_siret(siret)
    return clean[:9] if len(clean)>=9 else clean

@dataclass
class EntityToCheck:
    name: str
    siren: Optional[str] = None
    siret: Optional[str] = None

@dataclass
class RegisteredEntity:
    id: str
    name: str
    entity_type: str
    siren: Optional[str] = None
    siret: Optional[str] = None
    dossier_ref: Optional[str] = None
    avocat_name: Optional[str] = None
    status: Optional[str] = None

@dataclass
class ConflictMatch:
    entity: RegisteredEntity
    match_type: str
    similarity: float
    risk: str
    reason: str

@dataclass
class ConflictCheckResult:
    entity_checked: EntityToCheck
    result: str
    has_conflict: bool
    conflicts: list
    checked_at: datetime
    summary: str
    recommendation: str

class ConflictEngine:
    SIMILARITY_THRESHOLD_HIGH = 0.92
    SIMILARITY_THRESHOLD_MED = 0.80

    def __init__(self, registered_entities: list):
        self.entities = registered_entities

    def check(self, entity: EntityToCheck) -> ConflictCheckResult:
        conflicts = []
        norm_name = normalize_name(entity.name)
        norm_siren = normalize_siren(entity.siren or "")
        norm_siret = normalize_siret(entity.siret or "")
        for registered in self.entities:
            reg_norm = normalize_name(registered.name)
            reg_siren = normalize_siren(registered.siren or "")
            reg_siret = normalize_siret(registered.siret or "")
            conflict = None
            if norm_siret and reg_siret and norm_siret == reg_siret:
                conflict = ConflictMatch(entity=registered,match_type="siret_exact",similarity=1.0,risk="critique",reason=f"SIRET identique ({entity.siret})")
            elif norm_siren and reg_siren and norm_siren == reg_siren:
                conflict = ConflictMatch(entity=registered,match_type="siren_exact",similarity=1.0,risk="critique",reason=f"SIREN identique ({entity.siren})")
            elif norm_name and reg_norm and norm_name == reg_norm:
                conflict = ConflictMatch(entity=registered,match_type="nom_exact",similarity=1.0,risk="critique",reason=f"Nom identique: {entity.name}")
            elif norm_name and reg_norm:
                sim = SequenceMatcher(None, norm_name, reg_norm).ratio()
                if sim >= self.SIMILARITY_THRESHOLD_HIGH:
                    conflict = ConflictMatch(entity=registered,match_type="nom_similaire",similarity=sim,risk="critique",reason=f"Nom quasi-identique ({sim:.0%}): {registered.name}")
                elif sim >= self.SIMILARITY_THRESHOLD_MED:
                    conflict = ConflictMatch(entity=registered,match_type="nom_similaire",similarity=sim,risk="eleve",reason=f"Nom similaire ({sim:.0%}): {registered.name}")
            if conflict: conflicts.append(conflict)
        if not conflicts:
            return ConflictCheckResult(entity_checked=entity,result="vert",has_conflict=False,conflicts=[],checked_at=datetime.utcnow(),summary="Aucun conflit détecté.",recommendation="Vous pouvez accepter le mandat.")
        risks = [c.risk for c in conflicts]
        if "critique" in risks:
            return ConflictCheckResult(entity_checked=entity,result="rouge",has_conflict=True,conflicts=conflicts,checked_at=datetime.utcnow(),summary=f"{len(conflicts)} conflit(s) critique(s).",recommendation="REFUS OBLIGATOIRE ou saisine du Bâtonnier (RIN Art. 4).")
        return ConflictCheckResult(entity_checked=entity,result="orange",has_conflict=True,conflicts=conflicts,checked_at=datetime.utcnow(),summary=f"{len(conflicts)} risque(s) potentiel(s).",recommendation="Vérification manuelle approfondie requise.")

def conflict_result_to_dict(result: ConflictCheckResult) -> dict:
    return {"entity_checked": {"name": result.entity_checked.name,"siren": result.entity_checked.siren,"siret": result.entity_checked.siret},"result": result.result,"has_conflict": result.has_conflict,"conflicts": [{"matched_name": c.entity.name,"client_name": c.entity.name,"client_type": c.entity.entity_type,"match_type": c.match_type,"similarity": round(c.similarity,3),"risk": c.risk,"reason": c.reason,"siren": c.entity.siren,"dossier_ref": c.entity.dossier_ref} for c in result.conflicts],"checked_at": result.checked_at.isoformat(),"summary": result.summary,"recommendation": result.recommendation}
