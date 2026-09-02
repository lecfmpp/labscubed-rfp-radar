# -*- coding: utf-8 -*-
"""Critérios de qualificação de RFPs para a LabsCubed.
Produtos: CubeTen (tração, plásticos rígidos, 10kN, ASTM D638/ISO 527),
CubeOne (tração/rasgo, borrachas e elastômeros, 1kN, ASTM D412/ISO 37/D624),
CubeFlex (flexão, ASTM D790/ISO 178) + Portal na nuvem + AI Suite.
"""

# --- CAMADA 1: CPV (filtro barato, roda sobre 100% dos avisos) -------------
# Casados por PREFIXO: 38542000 (servo-hidraulico) e 38541000 pertencem a 3854.
CPV_CORE_PREFIX = (
    "3854",   # 385400xx Maquinas e aparelhos de ensaio e medicao (inc. 38542000 servo-hidraulico)
    "3850",   # 385000xx Aparelhos de verificacao e ensaio
    "3897",   # 389700xx Simulador tecnico-cientifico de investigacao e ensaio
    "3890",   # 389000xx Instrumentos diversos de avaliacao ou ensaio
    "38400",  # 384000xx Instrumentos de verificacao de caracteristicas fisicas
)
CPV_CORE = {"38540000", "38542000", "38500000", "38970000", "38900000", "38400000"}
CPV_BROAD_PREFIX = ("3800", "3843", "4200", "4800", "7190", "7300")
CPV_BROAD = {           # match fraco: só qualifica se houver keyword
    "38000000",  # Equipamento de laboratório, ótico e de precisão
    "38430000",  # Aparelhos de deteção e análise
    "42000000",  # Maquinaria industrial
    "48000000",  # Software (Portal / AI Suite)
    "71900000",  # Serviços de laboratório
    "73000000",  # I&D
}

# --- CAMADA 2: palavras-chave multi-idioma --------------------------------
KW_STRONG = [  # sozinhas já indicam o produto
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
KW_NORMS = [  # normas = sinal muito forte e inequívoco
    "astm d638", "astm d412", "astm d624", "astm d790", "astm d882",
    "iso 527", "iso 37", "iso 34", "iso 178", "din en iso 527", "din en iso 178",
]
KW_SUPPORT = [  # reforçam, não qualificam sozinhas
    "extensometer", "extensômetro", "extensomètre", "probenwechsler",
    "specimen", "probekörper", "éprouvette", "probeta",
    "kraftaufnehmer", "load cell", "célula de carga",
    "prüfkörper", "dehnung", "kunststoff", "elastomer", "polymer",
    "gummi", "rubber", "plastics", "plásticos", "automated", "automatisiert",
    "roboter", "robotic", "autosampler",
]

# --- CAMADA 3: exclusões (fora do envelope técnico da LabsCubed) ----------
KW_NEGATIVE = [
    "beton", "concrete", "asphalt", "bitumen", "zement", "cement",
    "bodenmechanik", "soil", "geotechni", "gestein", "rock mechanics",
    "schweißnaht", "weld", "rebar", "bewehrung", "stahlbau",
    "härteprüf", "hardness test", "durometer",       # dureza: não é produto deles
    "charpy", "kerbschlag", "impact test",           # impacto: não é produto deles
    "wartungsvertrag", "maintenance contract", "reparatur", "instandhaltung",
    "kalibrier", "calibration service", "ersatzteil", "spare part",
]

WEIGHTS = {"cpv_core": 35, "cpv_broad": 12, "kw_strong": 30,
           "kw_norm": 40, "kw_support": 5, "negative": -30}
SCORE_HOT, SCORE_WARM = 60, 40   # >=60 revisar hoje | 40-59 triagem | <40 descartar

# --- CRIVO DE DESQUALIFICACAO -------------------------------------------
# Distinto de "nao deu match": aqui o edital E de ensaio de materiais, mas cai
# fora do envelope tecnico dos produtos. Vira disqualified=true na BD, com razao.
DISQUALIFIERS = [
    (["beton", "concrete", "asphalt", "bitumen", "zement", "cement",
      "geotechni", "soil mechanic", "bodenmechanik", "gestein"],
     "material fora do envelope: betao/asfalto/solo"),
    (["stahlbau", "rebar", "bewehrung", "metallprüf", "metal testing",
      "schweißnaht", "weld test"],
     "material fora do envelope: metal/estrutural"),
    (["härteprüf", "hardness test", "durometer", "rockwell", "vickers", "brinell"],
     "tipo de ensaio nao suportado: dureza"),
    (["charpy", "kerbschlag", "izod", "impact test", "schlagzäh"],
     "tipo de ensaio nao suportado: impacto"),
    (["dauerschwing", "fatigue test", "ermüdungsprüf", "kriechprüf", "creep test"],
     "tipo de ensaio nao suportado: fadiga/fluencia"),
    (["wartungsvertrag", "maintenance contract", "instandhaltung",
      "kalibrierdienst", "calibration service", "ersatzteil", "spare part"],
     "objeto e servico/pecas, nao equipamento"),
]
# Forca acima de 10 kN (CubeTen e o topo da gama).
FORCE_RE = r"(\d{2,4})\s*(?:kn|kilonewton)"
MAX_KN = 10
