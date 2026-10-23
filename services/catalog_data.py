"""Curadoria local: exercícios principais e alimentos usados pelos geradores.

Os nomes em português e os padrões de movimento são curadoria do FitOS sobre o
catálogo ExerciseDB. Os valores nutricionais vêm sempre da TACO, nunca daqui.
"""

# (nome no ExerciseDB, nome em português, padrão de movimento, dificuldade)
CORE_EXERCISES: list[tuple[str, str, str, str]] = [
    # peito
    ("barbell bench press", "Supino reto com barra", "chest_press", "intermediário"),
    ("dumbbell bench press", "Supino reto com halteres", "chest_press", "iniciante"),
    ("machine chest press", "Supino na máquina", "chest_press", "iniciante"),
    ("push-up", "Flexão de braços", "chest_press", "iniciante"),
    ("barbell incline bench press", "Supino inclinado com barra", "chest_incline", "intermediário"),
    ("dumbbell incline bench press", "Supino inclinado com halteres", "chest_incline", "iniciante"),
    ("machine incline chest press", "Supino inclinado na máquina", "chest_incline", "iniciante"),
    ("dumbbell fly", "Crucifixo com halteres", "chest_fly", "iniciante"),
    ("machine seated fly", "Crucifixo na máquina (voador)", "chest_fly", "iniciante"),
    ("cable middle fly", "Crossover na polia", "chest_fly", "intermediário"),
    # costas
    ("cable pulldown", "Puxada frontal na polia", "vertical_pull", "iniciante"),
    ("twin handle parallel grip lat pulldown", "Puxada com pegada neutra", "vertical_pull", "iniciante"),
    ("machine front pulldown", "Puxada frontal na máquina", "vertical_pull", "iniciante"),
    ("assisted pull-up", "Barra fixa assistida", "vertical_pull", "iniciante"),
    ("pull-up", "Barra fixa", "vertical_pull", "avançado"),
    ("cable seated row", "Remada sentada na polia", "row", "iniciante"),
    ("machine seated row", "Remada sentada na máquina", "row", "iniciante"),
    ("barbell bent over row", "Remada curvada com barra", "row", "intermediário"),
    ("dumbbell bent over row", "Remada curvada com halteres", "row", "iniciante"),
    ("inverted row", "Remada invertida", "row", "iniciante"),
    # pernas
    ("barbell full squat", "Agachamento livre com barra", "squat", "intermediário"),
    ("smith squat", "Agachamento no Smith", "squat", "iniciante"),
    ("dumbbell goblet squat", "Agachamento goblet", "squat", "iniciante"),
    ("sled hack squat", "Agachamento hack", "squat", "intermediário"),
    ("sled 45° leg press", "Leg press 45°", "leg_press", "iniciante"),
    ("barbell romanian deadlift", "Levantamento terra romeno com barra", "hinge", "intermediário"),
    ("dumbbell romanian deadlift", "Levantamento terra romeno com halteres", "hinge", "iniciante"),
    ("barbell deadlift", "Levantamento terra", "hinge", "avançado"),
    ("dumbbell lunge", "Afundo com halteres", "lunge", "iniciante"),
    ("dumbbell rear lunge", "Afundo reverso com halteres", "lunge", "iniciante"),
    ("split squats", "Agachamento búlgaro / afundo estático", "lunge", "iniciante"),
    ("machine leg extension", "Cadeira extensora", "knee_ext", "iniciante"),
    ("machine lying leg curl", "Mesa flexora", "knee_flex", "iniciante"),
    ("machine seated leg curl", "Cadeira flexora", "knee_flex", "iniciante"),
    ("barbell glute bridge", "Elevação de quadril com barra", "glute", "iniciante"),
    ("machine seated hip abduction", "Cadeira abdutora", "glute", "iniciante"),
    ("machine standing calf raise", "Panturrilha em pé na máquina", "calf", "iniciante"),
    ("dumbbell standing calf raise", "Panturrilha em pé com halteres", "calf", "iniciante"),
    ("sled 45° calf press", "Panturrilha no leg press", "calf", "iniciante"),
    # ombros
    ("dumbbell seated shoulder press", "Desenvolvimento com halteres", "shoulder_press", "iniciante"),
    ("machine shoulder press", "Desenvolvimento na máquina", "shoulder_press", "iniciante"),
    ("barbell seated overhead press", "Desenvolvimento com barra sentado", "shoulder_press", "intermediário"),
    ("dumbbell lateral raise", "Elevação lateral com halteres", "lateral_raise", "iniciante"),
    ("cable lateral raise", "Elevação lateral na polia", "lateral_raise", "intermediário"),
    ("dumbbell rear fly", "Crucifixo inverso com halteres", "rear_delt", "iniciante"),
    ("machine seated reverse fly", "Crucifixo inverso na máquina", "rear_delt", "iniciante"),
    # braços
    ("barbell curl", "Rosca direta com barra", "biceps", "iniciante"),
    ("dumbbell alternate biceps curl", "Rosca alternada com halteres", "biceps", "iniciante"),
    ("dumbbell hammer curl", "Rosca martelo", "biceps", "iniciante"),
    ("cable curl", "Rosca na polia", "biceps", "iniciante"),
    ("cable pushdown", "Tríceps na polia (barra)", "triceps", "iniciante"),
    ("cable pushdown (with rope attachment)", "Tríceps corda", "triceps", "iniciante"),
    ("dumbbell seated triceps extension", "Tríceps francês com halter", "triceps", "iniciante"),
    ("barbell lying triceps extension", "Tríceps testa", "triceps", "intermediário"),
    ("triceps dip", "Mergulho (paralelas)", "triceps", "intermediário"),
    # core e cardio
    ("crunch floor", "Abdominal no solo", "core", "iniciante"),
    ("dead bug", "Dead bug", "core", "iniciante"),
    ("weighted front plank", "Prancha com carga", "core", "intermediário"),
    ("cable kneeling crunch", "Abdominal ajoelhado na polia", "core", "intermediário"),
    ("hanging leg raise", "Elevação de pernas na barra", "core", "avançado"),
    ("walking on incline treadmill", "Caminhada inclinada na esteira", "cardio", "iniciante"),
    ("stationary bike walk", "Bicicleta ergométrica", "cardio", "iniciante"),
]

# O catálogo tem nomes repetidos; em alguns, a primeira entrada aponta para um GIF removido (404) no
# ExerciseDB. Nome do exercício curado → source_id da entrada duplicada cuja mídia funciona (conferido em
# 23/10/2026).
CORE_MEDIA_FROM = {
    "assisted pull-up": "kiJ4Z2K",
    "cable seated row": "fUBheHs",
    "inverted row": "bZGHsAZ",
    "barbell romanian deadlift": "wQ2c4XD",
    "barbell lying triceps extension": "iZop9xO",
    "cable kneeling crunch": "WW95auq",
}

SLOT_LABELS = {
    "chest_press": "Empurrar horizontal", "chest_incline": "Empurrar inclinado", "chest_fly": "Adução de ombro",
    "vertical_pull": "Puxar vertical", "row": "Puxar horizontal", "squat": "Agachar", "leg_press": "Leg press",
    "hinge": "Dobrar quadril", "lunge": "Unilateral de pernas", "knee_ext": "Extensão de joelho",
    "knee_flex": "Flexão de joelho", "glute": "Glúteos", "calf": "Panturrilha",
    "shoulder_press": "Empurrar vertical", "lateral_raise": "Deltoide lateral", "rear_delt": "Deltoide posterior",
    "biceps": "Bíceps", "triceps": "Tríceps", "core": "Core", "cardio": "Cardio",
}

# Orientação geral por padrão de movimento (texto do FitOS, não da fonte da mídia)
COMMON_ERRORS = {
    "chest_press": "Tirar os ombros do banco; descer a barra rápido e quicar no peito; abrir os cotovelos a 90° do tronco.",
    "chest_incline": "Inclinação exagerada do banco (vira desenvolvimento); arquear demais a lombar; perder o controle na descida.",
    "chest_fly": "Estender totalmente os cotovelos com carga; descer além do confortável para o ombro; usar impulso.",
    "vertical_pull": "Puxar com o tronco jogando para trás; levar a barra atrás da nuca; não controlar a subida.",
    "row": "Arredondar a coluna; puxar com impulso do quadril; encolher os ombros em direção às orelhas.",
    "squat": "Joelhos colapsando para dentro; calcanhares saindo do chão; perder a neutralidade da coluna no fundo.",
    "leg_press": "Tirar o quadril do encosto no fundo; travar os joelhos no topo; descer além do que a lombar permite.",
    "hinge": "Arredondar a lombar; afastar a barra/halteres das pernas; transformar o movimento em agachamento.",
    "lunge": "Joelho da frente colapsando para dentro; passo curto demais; tronco desabando à frente.",
    "knee_ext": "Usar impulso; travar e bater o joelho no topo; carga acima do controle.",
    "knee_flex": "Tirar o quadril do banco; encurtar a amplitude; voltar o peso sem controle.",
    "glute": "Hiperestender a lombar no topo em vez de estender o quadril; pés muito longe do corpo.",
    "calf": "Amplitude curta; quicar no fundo; dobrar os joelhos para ajudar.",
    "shoulder_press": "Arquear a lombar; descer com os cotovelos muito atrás do corpo; travar os cotovelos com força.",
    "lateral_raise": "Subir acima da linha dos ombros com impulso; encolher o trapézio; carga excessiva.",
    "rear_delt": "Usar as costas e o impulso em vez do deltoide posterior; amplitude curta.",
    "biceps": "Balançar o tronco; mover os cotovelos para frente; descer sem controle.",
    "triceps": "Abrir os cotovelos; usar o peso do corpo para empurrar; amplitude curta.",
    "core": "Puxar o pescoço com as mãos; prender a respiração; perder a posição neutra da lombar.",
    "cardio": "Intensidade alta logo no início; segurar no corrimão da esteira e anular a inclinação.",
}

# Agrupamento do campo "equipamento" do ExerciseDB em categorias do perfil
EQUIPMENT_GROUPS = {
    "barra": {"barbell", "ez bar", "olympic barbell", "trap bar"},
    "halteres": {"dumbbell"},
    "máquinas": {"leverage machine", "sled machine", "smith machine", "assisted"},
    "polia/cabos": {"cable", "rope"},
    "peso corporal": {"bodyweight", "weighted"},
    "elásticos": {"resistance band"},
    "kettlebell": {"kettlebell"},
    "cardio": {"stationary bike", "elliptical machine", "stepmill machine"},
}
EQUIPMENT_CHOICES = list(EQUIPMENT_GROUPS)

# Alimentos curados. (taco_id, nome curto, grupo de substituição, estado, taco_id do cru, fator comestível)
# Grupos: proteina, ovo, leguminosa, cereal, tuberculo, pao, fruta, vegetal, laticinio, gordura,
# oleaginosa, acucar
CORE_FOODS: list[tuple[int, str, str, str, int | None, float | None]] = [
    (3, "Arroz branco cozido", "cereal", "cozido", 4, None),
    (4, "Arroz branco cru", "cereal", "cru", None, None),
    (1, "Arroz integral cozido", "cereal", "cozido", 2, None),
    (2, "Arroz integral cru", "cereal", "cru", None, None),
    (7, "Aveia em flocos", "cereal", "pronto", None, None),
    (40, "Macarrão (peso cru)", "cereal", "cru", None, None),
    (533, "Cuscuz de milho cozido", "cereal", "cozido", 43, None),
    (43, "Fubá / flocão de milho", "cereal", "cru", None, None),
    (53, "Pão francês", "pao", "pronto", None, None),
    (52, "Pão de forma integral", "pao", "pronto", None, None),
    (121, "Farinha de mandioca", "cereal", "pronto", None, None),
    (91, "Batata inglesa cozida", "tuberculo", "cozido", 92, None),
    (92, "Batata inglesa crua", "tuberculo", "cru", None, 0.85),
    (88, "Batata-doce cozida", "tuberculo", "cozido", 89, None),
    (89, "Batata-doce crua", "tuberculo", "cru", None, 0.85),
    (129, "Mandioca cozida", "tuberculo", "cozido", 130, None),
    (130, "Mandioca crua", "tuberculo", "cru", None, 0.75),
    (561, "Feijão carioca cozido", "leguminosa", "cozido", 562, None),
    (562, "Feijão carioca cru", "leguminosa", "cru", None, None),
    (567, "Feijão preto cozido", "leguminosa", "cozido", 568, None),
    (568, "Feijão preto cru", "leguminosa", "cru", None, None),
    (577, "Lentilha cozida", "leguminosa", "cozido", 578, None),
    (578, "Lentilha crua", "leguminosa", "cru", None, None),
    (410, "Peito de frango grelhado", "proteina", "cozido", 409, None),
    (408, "Peito de frango cozido", "proteina", "cozido", 409, None),
    (409, "Peito de frango cru (sem pele)", "proteina", "cru", None, None),
    (398, "Coxa de frango cozida (sem pele)", "proteina", "cozido", 399, None),
    (399, "Coxa de frango crua (sem pele)", "proteina", "cru", None, 0.75),
    (377, "Patinho grelhado", "proteina", "cozido", 376, None),
    (376, "Patinho cru", "proteina", "cru", None, None),
    (326, "Acém moído cozido", "proteina", "cozido", 327, None),
    (327, "Acém moído cru", "proteina", "cru", None, None),
    (371, "Músculo bovino cozido", "proteina", "cozido", 372, None),
    (372, "Músculo bovino cru", "proteina", "cru", None, None),
    (356, "Fígado bovino grelhado", "proteina", "cozido", 355, None),
    (355, "Fígado bovino cru", "proteina", "cru", None, None),
    (432, "Lombo suíno assado", "proteina", "cozido", 433, None),
    (433, "Lombo suíno cru", "proteina", "cru", None, None),
    (301, "Merluza assada", "proteina", "cozido", 302, None),
    (302, "Filé de merluza cru", "proteina", "cru", None, None),
    (319, "Sardinha em conserva (óleo)", "proteina", "pronto", None, None),
    (277, "Atum em conserva (óleo)", "proteina", "pronto", None, None),
    (584, "Tofu", "proteina", "pronto", None, None),
    (488, "Ovo cozido", "ovo", "cozido", 489, None),
    (489, "Ovo cru", "ovo", "cru", None, 0.88),
    (458, "Leite integral", "laticinio", "pronto", None, None),
    (457, "Leite desnatado UHT", "laticinio", "pronto", None, None),
    (448, "Iogurte natural", "laticinio", "pronto", None, None),
    (449, "Iogurte natural desnatado", "laticinio", "pronto", None, None),
    (461, "Queijo minas frescal", "laticinio", "pronto", None, None),
    (463, "Queijo mussarela", "laticinio", "pronto", None, None),
    (469, "Ricota", "laticinio", "pronto", None, None),
    (468, "Requeijão cremoso", "laticinio", "pronto", None, None),
    (260, "Azeite de oliva", "gordura", "pronto", None, None),
    (272, "Óleo de soja", "gordura", "pronto", None, None),
    (261, "Manteiga com sal", "gordura", "pronto", None, None),
    (558, "Amendoim torrado", "oleaginosa", "pronto", None, None),
    (182, "Banana prata", "fruta", "pronto", None, 0.65),
    (179, "Banana nanica", "fruta", "pronto", None, 0.65),
    (222, "Maçã fuji", "fruta", "pronto", None, 0.90),
    (214, "Laranja pera", "fruta", "pronto", None, 0.70),
    (225, "Mamão formosa", "fruta", "pronto", None, 0.70),
    (235, "Melancia", "fruta", "pronto", None, 0.55),
    (231, "Manga Tommy", "fruta", "pronto", None, 0.65),
    (200, "Goiaba vermelha", "fruta", "pronto", None, 0.90),
    (164, "Abacaxi", "fruta", "pronto", None, 0.55),
    (239, "Morango", "fruta", "pronto", None, 0.95),
    (163, "Abacate", "fruta", "pronto", None, 0.65),
    (100, "Brócolis cozido", "vegetal", "cozido", 101, None),
    (101, "Brócolis cru", "vegetal", "cru", None, 0.60),
    (110, "Cenoura crua", "vegetal", "pronto", None, 0.90),
    (157, "Tomate", "vegetal", "pronto", None, 0.95),
    (78, "Alface crespa", "vegetal", "pronto", None, 0.75),
    (70, "Abobrinha cozida", "vegetal", "cozido", 71, None),
    (71, "Abobrinha crua", "vegetal", "cru", None, 0.95),
    (64, "Abóbora cabotiá cozida", "vegetal", "cozido", 65, None),
    (65, "Abóbora cabotiá crua", "vegetal", "cru", None, 0.75),
    (112, "Chuchu cozido", "vegetal", "cozido", 113, None),
    (113, "Chuchu cru", "vegetal", "cru", None, 0.85),
    (149, "Repolho cru", "vegetal", "pronto", None, 0.85),
    (142, "Pepino", "vegetal", "pronto", None, 0.90),
    (107, "Cebola", "vegetal", "pronto", None, 0.90),
    (98, "Beterraba crua", "vegetal", "pronto", None, 0.85),
    (507, "Mel", "acucar", "pronto", None, None),
]

EDIBLE_SOURCE = "Fator de correção típico de técnica dietética — estimativa editável"
YIELD_SOURCE = "Estimado pela umidade TACO (matéria seca conservada) — editável"

# itens tipicamente vendidos por unidade/volume: peso médio para conversão (editável no produto)
DEFAULT_PRODUCTS = [
    # (nome, categoria, taco_id do alimento comprado, gramas por unidade, densidade g/ml)
    ("Peito de frango (filé)", "Carnes", 409, None, None),
    ("Patinho", "Carnes", 376, None, None),
    ("Acém moído", "Carnes", 327, None, None),
    ("Coxa de frango", "Carnes", 399, None, None),
    ("Ovo branco", "Ovos", 489, 50.0, None),
    ("Arroz branco tipo 1", "Mercearia", 4, None, None),
    ("Feijão carioca", "Mercearia", 562, None, None),
    ("Feijão preto", "Mercearia", 568, None, None),
    ("Aveia em flocos", "Mercearia", 7, None, None),
    ("Macarrão", "Mercearia", 40, None, None),
    ("Pão francês", "Padaria", 53, 50.0, None),
    ("Leite integral", "Laticínios", 458, None, 1.03),
    ("Banana prata", "Hortifrúti", 182, None, None),
    ("Batata-doce", "Hortifrúti", 89, None, None),
    ("Azeite de oliva", "Mercearia", 260, None, 0.91),
    ("Óleo de soja", "Mercearia", 272, None, 0.92),
]

# Índice de cocção (peso pronto / peso cru) de referência em técnica dietética.
# Usado no lugar da estimativa por umidade quando a amostra TACO cozida não é comparável
# (ex.: feijão pesado com caldo). Valores aproximados e editáveis por alimento.
YIELD_REFERENCE = {
    3: 2.8, 1: 2.6, 533: 2.0, 561: 2.4, 567: 2.4, 577: 2.4,
    91: 0.98, 88: 0.95, 129: 1.0, 64: 0.85, 70: 0.85, 100: 0.95, 112: 0.9,
    410: 0.70, 408: 0.73, 398: 0.71, 377: 0.65, 326: 0.71, 371: 0.65, 356: 0.70,
    432: 0.70, 301: 0.75, 488: 1.0,
}
YIELD_REFERENCE_SOURCE = "Índice de cocção de referência (técnica dietética) — estimativa editável"
