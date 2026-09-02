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
    # DE
    "zugprüfmaschine", "universalprüfmaschine", "werkstoffprüfmaschine",
    "materialprüfmaschine", "zugversuch", "zugprüfung", "biegeprüfung",
    "reißfestigkeit", "zugfestigkeit", "prüfmaschine",
    # EN
    "tensile test", "tensile testing", "universal testing machine",
    "materials testing machine", "material testing machine", "flexural test",
    "tear strength", "tensile strength", "elongation at break",
    # FR / ES / PT / IT
    "machine d'essai de traction", "essai de traction",
    "máquina de ensayo de tracción", "ensayo de tracción",
    "máquina de ensaio de tração", "macchina di prova a trazione",
]
KW_NORMS = [  # standards are the strongest, least ambiguous signal
    "astm d638", "astm d412", "astm d624", "astm d790", "astm d882",
    "iso 527", "iso 37", "iso 34", "iso 178", "din en iso 527", "din en iso 178",
]
KW_SUPPORT = [  # reinforce a match, never qualify on their own
    "extensometer", "extensômetro", "extensomètre", "probenwechsler",
    "specimen", "probekörper", "éprouvette", "probeta",
    "kraftaufnehmer", "load cell", "célula de carga",
    "prüfkörper", "dehnung", "kunststoff", "elastomer", "polymer",
    "gummi", "rubber", "plastics", "plásticos", "automated", "automatisiert",
    "roboter", "robotic", "autosampler",
]

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
