# -*- coding: utf-8 -*-
"""Scoring engine shared by both sources (Germany + TED)."""
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
        pts += WEIGHTS["cpv_core"];  why.append(f"core CPV {sorted(core)}")
    elif broad:
        pts += WEIGHTS["cpv_broad"]; why.append(f"broad CPV {sorted(broad)}")

    hits_n = [k for k in KW_NORMS    if k in text]
    hits_s = [k for k in KW_STRONG   if k in text]
    hits_p = [k for k in KW_SUPPORT  if k in text]
    hits_x = [k for k in KW_NEGATIVE if k in text]

    if hits_n: pts += WEIGHTS["kw_norm"];   why.append(f"standard: {hits_n[:3]}")
    if hits_s: pts += WEIGHTS["kw_strong"]; why.append(f"strong term: {hits_s[:3]}")
    if hits_p: pts += min(len(hits_p), 4) * WEIGHTS["kw_support"]; why.append(f"supporting: {hits_p[:4]}")
    if hits_x: pts += WEIGHTS["negative"];  why.append(f"EXCLUSION: {hits_x[:3]}")

    # A broad CPV alone, with no keyword at all, does not qualify.
    if not (hits_n or hits_s) and not core:
        pts = min(pts, 25)

    tier = "HOT" if pts >= SCORE_HOT else "WARM" if pts >= SCORE_WARM else "COLD"
    return pts, tier, "; ".join(why)


def disqualify(title, description):
    """Technical screen: the notice is in our field but outside the envelope.
    Returns (True, reason) or (False, None)."""
    text = norm(f"{title} {description}")
    for terms, reason in DISQUALIFIERS:
        hit = [t for t in terms if t in text]
        if hit:
            return True, f"{reason} ({hit[0]})"
    for m in re.finditer(FORCE_RE, text):
        kn = int(m.group(1))
        if kn > MAX_KN:
            return True, f"requested force {kn} kN exceeds the {MAX_KN} kN maximum (CubeTen)"
    for m in re.finditer(r"(\d{4,})\s*%", text):
        if int(m.group(1)) > 1000:
            return True, f"elongation {m.group(1)}% exceeds the 1000% maximum"
    return False, None
