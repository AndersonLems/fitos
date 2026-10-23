"""Glossário de academia para a tradução automática (scripts/traduzir_instrucoes.py): PRE ajusta o inglês
antes do modelo, POST corrige os erros recorrentes dele ('dumbbell' → 'cabresto', 'kettlebell' → 'chaleira'…)."""
import re
PRE = [  # termo em inglês → termo de academia, antes de traduzir
    (r"\bbrace your (trunk|core|abs)\b", "tighten your abs"), (r"\boverhead\b", "above your head"),
    (r"\bswitch sides when the set calls for it\b", "switch sides"),
    (r"\bsmith machine\b", "Smith machine"), (r"\bez[- ]?(bar|barbell|curl bar)\b", "barra W"),
    (r"\btrap bar\b", "barra hexagonal"), (r"\bpull-?up bar\b", "barra fixa"), (r"\bbarbells?\b", "barra"),
    
    (r"\bmedicine ball\b", "medicine ball"), (r"\bstability ball\b", "bola suíça"), (r"\bbosu ball\b", "bosu"),
    (r"\bpreacher (bench|pad|curl bench)\b", "banco Scott"), (r"\blunges?\b", "afundo"),
    (r"\bcore\b", "abdômen"), (r"\btrunk\b", "tronco"), (r"\btraps\b", "trapézio"),
    (r"\bthe next rep\b", "a próxima repetição"), (r"\banother rep\b", "outra repetição"), (r"\breps?\b", "repetição"),
    (r"\bthe set\b", "a série"), (r"\bsuspension trainer\b", "TRX"), (r"\bleverage machine\b", "máquina articulada"),
    (r"\bface down\b", "de bruços"), (r"\bface up\b", "de barriga para cima"), (r"\bD-handle\b", "puxador D"),
    (r"\bbrace your (trunk|core|abs)\b", "tighten your abs"), (r"\bhinge (forward )?at (the|your) hips\b", "lean forward from the hips"),
    (r"^Lie (face|on)\b", r"Lie down \1"), (r"\blead foot\b", "front foot"), (r"\bleg drive\b", "push from the legs"),
    (r"\b(settle|lie) (onto|on) your (stomach|belly)\b", "lie face down"), (r"\bab wheel\b|\bwheel roller\b", "roda abdominal"),
]
POST = [  # erros recorrentes do modelo
    (r"\bhaltere\b", "halter"),
    (r"\bAcomodem-se\b", "Acomode-se"), (r"\bEnfrente\b", "Fique de frente para"),
    (r"\b(firmemente )?plantad([oa]s?)\b", r"apoiad\2"), (r"\bsobre a largura (do|dos) ombros?\b", "na largura dos ombros"),
    (r"\bsobre a largura (do|dos) (quadril|quadris)\b", "na largura do quadril"), (r"\bLigue\b", "Prenda"), (r"\bligue\b", "prenda"),
    (r"\baderência\b", "pegada"), (r"\bum aperto\b", "uma pegada"), (r"\baperto\b", "pegada"),
    (r"\bpegas\b", "pegadores"), (r"\bpélvis\b", "pelve"), (r"\bnúcleo\b", "abdômen"),
    (r"\bLevante-se e coloque\b", "Fique em pé e coloque"), (r"\bLevante e coloque\b", "Fique em pé e coloque"),
    (r"\buma (pequena|ligeira|leve) curva nos cotovelos\b", "os cotovelos levemente flexionados"),
    (r"\bo bar\b", "a barra"), (r"\bum bar\b", "uma barra"), (r"\bdo bar\b", "da barra"), (r"\bno bar\b", "na barra"),
    (r"\btrancad([oa]s?)\b", r"travad\1"),
    (r"\b(cabrestos|cabrestantes|cabides|suspensórios)\b", "halteres"), (r"\b(cabresto|cabrestante|cabide)\b", "halter"),
    (r"\bbola de remédio\b", "medicine ball"), (r"\bbola medicinal\b", "medicine ball"), (r"\barma de braço\b", "arm blaster"),
    (r"\b(prato|placa) de peso\b", "anilha"), (r"\bfeixe\b", "viga"), (r"\bconfiguração mais\b", "posição mais"),
    (r"^Tome (o )?seu lugar\b", "Posicione-se"), (r"\bPuxador D\b", "puxador D"), (r"\bsua bunda\b", "o quadril"), (r"\bestômago\b", "abdômen"),
    (r"\b(tapete|colchoneta)\b", "colchonete"), (r"\bpegada pronado\b", "pegada pronada"), (r"\bpegada supinado\b", "pegada supinada"),
    (r"^Levantem-se e\b", "Fique em pé e"), (r"^Levantem-se\b", "Fique em pé"), (r"\bcoloquem\b", "coloque"),
    (r"\bsegurem\b", "segure"), (r"^Segurem\b", "Segure"), (r"^Reclinem\b", "Recline-se"), (r"\bposicionem\b", "posicione"),
    (r"\bjuntem\b", "junte"), (r"^Lie\b", "Deite-se"), (r"^Ligar\b", "Prenda"),
    (r"\bnas costas superiores\b", "na parte de cima das costas"),
    (r"\b(uma|a|na|da|o|um|no|do) (chaleira|campainha|sino)\b",
     lambda m: {"uma": "um", "a": "o", "na": "no", "da": "do"}.get(m.group(1), m.group(1)) + " kettlebell"),
    (r"\b(as|nas|das) (chaleiras|campainhas)\b", lambda m: m.group(1)[:-2] + "os kettlebells"),
    (r"\b(chaleira|campainha|sino)s?\b", "kettlebell"),
    (r"\bseu abdômen (ocupado|comprometido|ativado|acionado|engajado)\b", "o abdômen contraído"),
    (r"\babdômen (ocupado|comprometido|ativado|acionado|engajado)\b", "abdômen contraído"),
    (r"\bespinha\b", "coluna"), (r"\bpeito superior\b", "alto do peito"),
    (r"^Dobrar\b", "Dobre"), (r"^Segurar\b", "Segure"), (r"^Suspender-se\b", "Pendure-se"),
    (r"\bbarra puxada\b", "barra fixa"), (r"\bposição afundo\b", "posição de afundo"),
    (r"\bincline-se para (a )?frente (dos|nos) quadris\b", "incline o tronco à frente a partir do quadril"),
    (r"^Comece por deitar\b", "Comece deitado"), (r"^Comece por ficar de pé\b", "Fique em pé"),
    (r"\b(ao início|antes) de uma próxima\b", r"\1 da próxima"), (r"\bdo próximo representante\b", "da próxima repetição"),
    (r"\bmude de lado\b", "troque de lado"),
    (r"\b(cabrestos|halteres|haltere)\b", lambda m: "halter" if m.group(1) == "haltere" else "halteres"),
    (r"\bcabresto\b", "halter"), (r"\b(o|no|ao) volante\b", r"\1 roda"), (r"\bvolante\b", "roda"),
    (r"^Aproxime-se com\b", "Dê um passo à frente com"), (r"^Plantar\b", "Apoie"), (r"^Plante\b", "Apoie"), (r"\bacima da cabeça acima\b", "acima da cabeça"),
    # possessivos traduzidos ao pé da letra: "com seus pés" → "com os pés"
    (r"\bem (seus|suas|seu|sua) ", lambda m: {"seus": "nos ", "suas": "nas ", "seu": "no ", "sua": "na "}[m.group(1)]),
    (r"\bde (seus|suas|seu|sua) ", lambda m: {"seus": "dos ", "suas": "das ", "seu": "do ", "sua": "da "}[m.group(1)]),
    (r"\b(seus|suas|seu|sua) (?=(pés|pé|mãos|mão|braços|braço|pernas|perna|joelhos|joelho|cotovelos|cotovelo|ombros|ombro|quadris|quadril|costas|cabeça|coluna|corpo|tronco|peito|palmas|palma|dedos|calcanhares|coxas|pulsos|abdômen|glúteos|tornozelos)\b)",
     lambda m: {"seus": "os ", "suas": "as ", "seu": "o ", "sua": "a "}[m.group(1)]),
]

def pre(x):
    for a, b in PRE:
        x = re.sub(a, b, x, flags=re.I)
    return x

def post(x, src=""):
    x = " ".join(x.replace("▁", " ").split())
    if "kettlebell" not in src.lower():  # sem kettlebell na origem, "campainha" foi um halter mal traduzido
        x = re.sub(r"\b(uma|a|na|da) campainha\b", lambda m: {"uma": "um", "a": "o", "na": "no", "da": "do"}[m.group(1)] + " halter", x)
        x = re.sub(r"\bcampainhas\b", "halteres", x)
    for a, b in POST:
        x = re.sub(a, b, x)
    for a, b in [(r"\b(o|a|os|as) \1\b", r"\1"), (r"\bao o\b", "ao"), (r"\baos os\b", "aos"), (r"\bà a\b", "à"),
                 (r"\bpara (seus|suas) lados\b", "para os lados"), (r"\bLevantem\b", "Levante")]:
        x = re.sub(a, b, x)
    return x[0].upper() + x[1:] if x else x
