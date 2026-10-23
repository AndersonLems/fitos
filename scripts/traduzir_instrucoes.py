"""Gera assets/exercicios_pt_auto.json: tradução automática (Argos Translate, en→pt-BR) dos passos do catálogo.

Roda offline, fora do app, e só precisa ser repetido quando o catálogo mudar. As frases que já estão no
dicionário revisado (assets/exercicios_pt.json) ficam de fora. Dependências (não entram no requirements.txt):

    pip install --target /tmp/argos/lib ctranslate2 sentencepiece
    curl -L https://argos-net.com/v1/translate-en_pb-1_9.argosmodel -o pb.zip && unzip pb.zip -d /tmp/argos/model
    python3 scripts/traduzir_instrucoes.py /tmp/argos

Usa o modelo direto pelo CTranslate2 (o pacote argostranslate puxaria stanza/torch só para separar frases,
e os passos já vêm separados). scripts/glossario_traducao.py corrige os termos de academia.
"""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))
import glossario_traducao as g  # noqa: E402


def main(argos_dir: str) -> None:
    sys.path.insert(0, f"{argos_dir}/lib")
    import ctranslate2
    import sentencepiece as spm

    model = f"{argos_dir}/model/translate-en_pb-1_9"
    reviewed = json.loads((ROOT / "assets/exercicios_pt.json").read_text())
    db = sqlite3.connect(ROOT / "data/fitos.db")
    src = sorted({x.strip() for (text,) in db.execute("select instructions from exercises where instructions is not null")
                  for x in text.split("\n") if x.strip() and x.strip() not in reviewed})
    sp = spm.SentencePieceProcessor(model_file=f"{model}/sentencepiece.model")
    tr = ctranslate2.Translator(f"{model}/model", device="cpu", inter_threads=4)
    res = tr.translate_batch([sp.encode(g.pre(x), out_type=str) for x in src], beam_size=4, max_batch_size=32,
                             replace_unknowns=True)
    out = {x: g.post(sp.decode(r.hypotheses[0]).strip(), x) for x, r in zip(src, res)}
    (ROOT / "assets/exercicios_pt_auto.json").write_text(json.dumps(out, ensure_ascii=False, indent=0))
    print(f"{len(out)} frases traduzidas")


if __name__ == "__main__":
    main(sys.argv[1])
