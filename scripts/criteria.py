# -*- coding: utf-8 -*-
"""Qualification criteria for LabsCubed RFP detection.

Product envelope:
  CubeTen  — tensile, rigid plastics, 10 kN, ASTM D638 / ISO 527
  CubeOne  — tensile + tear, rubbers and elastomers, 1 kN, ASTM D412 / ISO 37 / D624
  CubeFlex — flexure, ASTM D790 / ISO 178
  Portal (cloud data management) + AI Suite
"""

# --- LAYER 1: CPV codes (cheap filter, runs over 100% of notices) ----------
# Matched by PREFIX: 38542000 (servo-hydraulic) and 38541000 belong to 3854.
CPV_CORE_PREFIX = (
    "3854",   # Machines and apparatus for testing and measuring (incl. servo-hydraulic)
    "3850",   # Checking and testing apparatus
    "3897",   # Research, testing and scientific technical simulator
    "3890",   # Miscellaneous evaluation or testing instruments
    "38400",  # Instruments for checking physical characteristics
)
CPV_CORE = {"38540000", "38542000", "38500000", "38970000", "38900000", "38400000"}

# Weak match: only qualifies when a keyword is also present.
CPV_BROAD_PREFIX = ("3800", "3843", "4200", "4800", "7190", "7300")
CPV_BROAD = {
    "38000000",  # Laboratory, optical and precision equipment
    "38430000",  # Detection and analysis apparatus
    "42000000",  # Industrial machinery
    "48000000",  # Software (Portal / AI Suite)
    "71900000",  # Laboratory services
    "73000000",  # R&D services
}

# --- LAYER 2: multilingual keywords ---------------------------------------
KW_STRONG = [  # on their own, these indicate the product
    # Primary = TENSILE + tear (rubber/plastic), the products we ship today.
    # Flexure (CubeFlex) is still in development, so it lives in KW_SUPPORT only.
    # DE
    "zugprüfmaschine", "universalprüfmaschine", "werkstoffprüfmaschine",
    "materialprüfmaschine", "zugversuch", "zugprüfung",
    "reißfestigkeit", "zugfestigkeit", "prüfmaschine",
    # EN (incl. US phrasing: "test machine/system", load frame, brands)
    "tensile test", "tensile testing", "universal testing machine",
    "universal test machine", "universal test system", "universal testing system",
    "materials testing machine", "material testing machine", "materials test system",
    "tensile tester", "tensile test machine",
    "load frame", "servo-hydraulic test", "servohydraulic test",
    "tear strength", "tensile strength", "elongation at break",
    # FR / ES / PT / IT
    "machine d'essai de traction", "essai de traction",
    "máquina de ensayo de tracción", "ensayo de tracción",
    "máquina de ensaio de tração", "macchina di prova a trazione",
]
KW_NORMS = [  # standards are the strongest, least ambiguous signal
    # PRIMARY — tensile & tear for rubber and plastics, across ASTM / ISO / JIS.
    # Naming one of these (e.g. ASTM D412) is the ICP's strongest buying signal.
    # plastics tensile
    "astm d638", "astm d882", "astm d1708", "iso 527", "jis k7161", "jis k7162", "jis k7127",
    "din en iso 527",
    # rubber / elastomer tensile + tear
    "astm d412", "astm d624", "iso 37", "iso 34", "jis k6251", "jis k6252",
]
# SECONDARY — flexure standards (CubeFlex still in development). Kept as support,
# so a flexure-only notice reinforces but never qualifies on its own.
KW_NORMS_FLEX = ["astm d790", "iso 178", "jis k7171", "din en iso 178"]
KW_SUPPORT = [  # reinforce a match, never qualify on their own
    "extensometer", "extensômetro", "extensomètre", "probenwechsler",
    "specimen", "probekörper", "éprouvette", "probeta",
    "kraftaufnehmer", "load cell", "célula de carga",
    "prüfkörper", "dehnung", "kunststoff", "elastomer", "polymer",
    "gummi", "rubber", "plastics", "plásticos", "automated", "automatisiert",
    "roboter", "robotic", "autosampler",
    # ICP materials — rubber, plastics AND composites are the target industries
    "composite", "composites", "film", "kautschuk", "borracha", "caucho",
    # US market vocabulary — brands, components, phrasing
    "instron", "mts systems", "bluehill", "crosshead", "test frame",
    "tensile", "grips", "klbf",
    # SECONDARY flexure signals (CubeFlex in development) — reinforce only
    "flexural", "flexure", "bending test", "biegeprüfung", "biegeversuch", "flexão",
] + KW_NORMS_FLEX

# --- LAYER 3: exclusions (outside the LabsCubed technical envelope) -------
KW_NEGATIVE = [
    "beton", "concrete", "asphalt", "bitumen", "zement", "cement",
    "bodenmechanik", "soil", "geotechni", "gestein", "rock mechanics",
    "schweißnaht", "weld", "rebar", "bewehrung", "stahlbau",
    "härteprüf", "hardness test", "durometer",       # hardness: not our product
    "charpy", "kerbschlag", "impact test",           # impact: not our product
    "wartungsvertrag", "maintenance contract", "reparatur", "instandhaltung",
    "kalibrier", "calibration service", "ersatzteil", "spare part",
]

WEIGHTS = {"cpv_core": 35, "cpv_broad": 12, "kw_strong": 30,
           "kw_norm": 40, "kw_support": 5, "negative": -30}
SCORE_HOT, SCORE_WARM = 60, 40   # >=60 review today | 40-59 triage | <40 discard

# --- DISQUALIFICATION SCREEN ---------------------------------------------
# Distinct from "did not match": the notice IS about materials testing, but falls
# outside the product envelope. Sets disqualified=true in the DB, with a reason.
DISQUALIFIERS = [
    (["beton", "concrete", "asphalt", "bitumen", "zement", "cement",
      "geotechni", "soil mechanic", "bodenmechanik", "gestein"],
     "material outside envelope: concrete/asphalt/soil"),
    (["stahlbau", "rebar", "bewehrung", "metallprüf", "metal testing",
      "schweißnaht", "weld test"],
     "material outside envelope: metal/structural"),
    (["härteprüf", "hardness test", "durometer", "rockwell", "vickers", "brinell"],
     "unsupported test type: hardness"),
    (["charpy", "kerbschlag", "izod", "impact test", "schlagzäh"],
     "unsupported test type: impact"),
    (["dauerschwing", "fatigue test", "ermüdungsprüf", "kriechprüf", "creep test"],
     "unsupported test type: fatigue/creep"),
    (["wartungsvertrag", "maintenance contract", "instandhaltung",
      "kalibrierdienst", "calibration service", "ersatzteil", "spare part"],
     "scope is service/parts, not equipment"),
]
# Force above 10 kN (CubeTen is the top of the range).
FORCE_RE = r"(\d{2,4})\s*(?:kn|kilonewton)"
MAX_KN = 10
