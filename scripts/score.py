# -*- coding: utf-8 -*-
"""Motor de pontuação partilhado pelas duas fontes (DE + TED)."""
import re, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from criteria import *

def norm(t): return re.sub(r"\s+", " ", (t or "").lower())

def score_notice(title, description, cpvs):
    text = norm(f"{title} {description}")
    cpvs = {str(c).strip()[:8] for c in cpvs if c}
    pts, why = 0, []

    core  = {c for c in cpvs if c.startswith(CPV_CORE_PREFIX)}
    broad = {c for c in cpvs if c.startswith(CPV_BROAD_PREFIX)} - core
    if core:
        pts += WEIGHTS["cpv_core"];  why.append(f"CPV core {sorted(core)}")
    elif broad:
        pts += WEIGHTS["cpv_broad"]; why.append(f"CPV amplo {sorted(broad)}")

    hits_n = [k for k in KW_NORMS   if k in text]
    hits_s = [k for k in KW_STRONG  if k in text]
    hits_p = [k for k in KW_SUPPORT if k in text]
    hits_x = [k for k in KW_NEGATIVE if k in text]

    if hits_n: pts += WEIGHTS["kw_norm"];   why.append(f"norma: {hits_n[:3]}")
    if hits_s: pts += WEIGHTS["kw_strong"]; why.append(f"termo forte: {hits_s[:3]}")
    if hits_p: pts += min(len(hits_p), 4) * WEIGHTS["kw_support"]; why.append(f"apoio: {hits_p[:4]}")
    if hits_x: pts += WEIGHTS["negative"];  why.append(f"EXCLUSAO: {hits_x[:3]}")

    # CPV amplo sozinho, sem nenhuma keyword, nao qualifica
    if not (hits_n or hits_s) and not core:
        pts = min(pts, 25)

    tier = "HOT" if pts >= SCORE_HOT else "WARM" if pts >= SCORE_WARM else "COLD"
    return pts, tier, "; ".join(why)


def disqualify(title, description):
    """Crivo tecnico: o edital e da nossa area mas cai fora do envelope.
    Devolve (True, razao) ou (False, None)."""
    text = norm(f"{title} {description}")
    for terms, reason in DISQUALIFIERS:
        hit = [t for t in terms if t in text]
        if hit:
            return True, f"{reason} ({hit[0]})"
    for m in re.finditer(FORCE_RE, text):
        kn = int(m.group(1))
        if kn > MAX_KN:
            return True, f"forca pedida {kn} kN excede o maximo de {MAX_KN} kN (CubeTen)"
    if re.search(r"(\d{4,})\s*%", text):
        for m in re.finditer(r"(\d{4,})\s*%", text):
            if int(m.group(1)) > 1000:
                return True, f"alongamento {m.group(1)}% excede o maximo de 1000%"
    return False, None
