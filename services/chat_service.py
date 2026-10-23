"""Chat contextual com ferramentas estruturadas.

O Gemini só PROPÕE ações por function calling. Cada proposta é validada por Pydantic e resolvida
contra o banco (nomes → IDs). Ações de leitura executam na hora; ações que alteram dados ficam
pendentes até o usuário confirmar. Nenhum código gerado pela IA é executado.
"""
from __future__ import annotations

import difflib
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import AIConversation, AIMessage, Exercise, Food, Profile
from services import gemini_service as gs
from services import nutrition_service as ns
from services import pricing_service as pr
from services import profile_service as ps
from services import shopping_service as sh
from services import workout_service as ws
from services.inventory_service import list_items, stock_summary_text
from services.ai_planner import profile_brief
from utils.units import comparable_price, fmt_brl

HISTORY_LIMIT = 12


# --------------------------------------------------------------------------- argumentos

class NoArgs(BaseModel):
    pass


class ConsultarPrecos(BaseModel):
    produto: str | None = None


class ConsultarCardapio(BaseModel):
    dia: int | None = Field(default=None, ge=1, le=31)


class GerarTreino(BaseModel):
    pedido: str | None = None


class SubstituirExercicio(BaseModel):
    exercicio_atual: str
    novo_exercicio: str


class RegistrarTreino(BaseModel):
    exercicio: str
    carga_kg: float = Field(ge=0, le=600)
    repeticoes: int = Field(ge=1, le=100)
    series: int = Field(default=1, ge=1, le=10)


class GerarCardapio(BaseModel):
    dias: Literal[1, 7, 15, 30, 31] = 7
    economico: bool = False
    orcamento: float | None = Field(default=None, gt=0, le=100000)


class SubstituirAlimento(BaseModel):
    alimento_atual: str
    novo_alimento: str


class AtualizarPreco(BaseModel):
    produto: str
    preco: float = Field(gt=0, le=100000)
    quantidade: float = Field(default=1, gt=0)
    unidade: Literal["kg", "g", "l", "ml", "un", "duzia"] = "kg"
    estabelecimento: str | None = None


class GerarListaCompras(BaseModel):
    dias: int | None = Field(default=None, ge=1, le=31)


class RegistrarPeso(BaseModel):
    peso_kg: float = Field(ge=30, le=300)


class MudarTreinoHoje(BaseModel):
    treino: str = Field(description="título ou letra do treino da ficha, ou 'descanso'")


TOOLS: dict[str, tuple[type[BaseModel], bool, str]] = {
    # nome: (args, altera_dados, descrição)
    "consultar_estoque": (NoArgs, False, "Lista os alimentos da despensa do usuário."),
    "consultar_precos": (ConsultarPrecos, False, "Preços cadastrados (melhor preço por produto e estabelecimento)."),
    "consultar_treino_hoje": (NoArgs, False, "Mostra o treino previsto para hoje e a ficha ativa."),
    "consultar_cardapio": (ConsultarCardapio, False, "Mostra o cardápio ativo (um dia ou o resumo)."),
    "gerar_treino": (GerarTreino, True, "Gera uma nova ficha de treino a partir do perfil (nova versão)."),
    "substituir_exercicio": (SubstituirExercicio, True, "Troca um exercício da ficha ativa por outro da biblioteca."),
    "registrar_treino": (RegistrarTreino, True, "Registra séries feitas hoje de um exercício (carga e repetições)."),
    "gerar_cardapio": (GerarCardapio, True, "Gera um novo cardápio (1, 7, 15, 30 ou 31 dias), opcionalmente econômico."),
    "substituir_alimento": (SubstituirAlimento, True, "Troca um alimento em todo o cardápio ativo."),
    "atualizar_preco": (AtualizarPreco, True, "Cadastra uma nova cotação de preço para um produto."),
    "gerar_lista_compras": (GerarListaCompras, True, "Cria a lista de compras do cardápio ativo descontando o estoque."),
    "registrar_peso": (RegistrarPeso, True, "Registra o peso de hoje."),
    "mudar_treino_hoje": (MudarTreinoHoje, True, "Troca o treino de hoje por outro dia da ficha ou descanso."),
}


def tool_declarations():
    from google.genai import types
    decls = []
    for name, (model, _, desc) in TOOLS.items():
        schema = model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        decl = {"name": name, "description": desc}
        if schema.get("properties"):
            decl["parameters_json_schema"] = schema
        decls.append(types.FunctionDeclaration(**decl))
    return [types.Tool(function_declarations=decls)]


# --------------------------------------------------------------------------- resolução de nomes

def _best(name: str, options: dict[str, object], cutoff: float = 0.55):
    key = (name or "").strip().lower()
    if key in options:
        return options[key]
    contains = [k for k in options if key and (key in k or k in key)]
    if len(contains) == 1:
        return options[contains[0]]
    m = difflib.get_close_matches(key, list(options), n=1, cutoff=cutoff)
    return options[m[0]] if m else None


def resolve_library_exercise(s: Session, name: str) -> Exercise | None:
    core = {(e.name_pt or e.name_original).lower(): e for e in ws.core_exercises(s)}
    hit = _best(name, core)
    if hit:
        return hit
    allx = {e.name_original.lower(): e for e in s.scalars(select(Exercise))}
    allx.update({e.name_pt.lower(): e for e in s.scalars(select(Exercise).where(Exercise.name_pt.is_not(None)))})
    return _best(name, allx, 0.7)


def resolve_food(s: Session, name: str) -> Food | None:
    foods = {(f.short_name or f.name).lower(): f for f in ns.core_foods(s)}
    return _best(name, foods)


# --------------------------------------------------------------------------- contexto

def build_context(s: Session, p: Profile) -> str:
    e = ps.estimate_energy(p)
    lines = [f"Perfil: {gs.compact(profile_brief(p))}",
             f"Meta estimada: {e.target_kcal} kcal, {e.protein_g} g proteína"
             + (" (provisória: falta " + ", ".join(e.provisional) + ")" if e.provisional else ""),
             f"Hoje: {date.today():%d/%m/%Y} ({ps.WEEKDAYS[date.today().weekday()]})"]
    plan = ws.active_plan(s, p.id)
    if plan:
        t = ws.todays_workout(s, p.id, plan)
        lines.append(f"Ficha ativa v{plan.version}: " + " | ".join(
            f"{d.title}: " + ", ".join((x.exercise.name_pt or x.exercise.name_original) for x in d.exercises)
            for d in plan.days))
        lines.append("Treino de hoje: " + (t.day.title if t.day else "descanso"))
    else:
        lines.append("Sem ficha de treino ativa.")
    mp = ns.active_plan(s, p.id)
    if mp:
        sm = ns.summarize(s, mp)
        lines.append(f"Cardápio ativo: {mp.name}, {mp.days} dias, custo calculado {fmt_brl(sm.total_cost)} "
                     f"(itens sem preço: {len(sm.unpriced)})")
    else:
        lines.append("Sem cardápio ativo.")
    if p.monthly_food_budget:
        lines.append(f"Orçamento mensal de alimentação: {fmt_brl(p.monthly_food_budget)}")
    lines.append("Estoque: " + stock_summary_text(list_items(s, p.id))[:700])
    return "\n".join(lines)


SYSTEM_CHAT = gs.SYSTEM_BASE + (
    " Você conversa dentro do FitOS e pode usar as ferramentas para consultar ou propor alterações. "
    "Ao propor uma alteração, chame a ferramenta: o sistema pedirá confirmação ao usuário antes de executar. "
    "Valores nutricionais e custos são calculados pelo sistema; não invente números nem preços. "
    "Se o usuário relatar dor, recomende não progredir carga e procurar avaliação profissional."
)


# --------------------------------------------------------------------------- execução

def _exec_read(s: Session, p: Profile, name: str, args: BaseModel) -> str:
    if name == "consultar_estoque":
        return stock_summary_text(list_items(s, p.id))
    if name == "consultar_precos":
        rows = []
        for c in pr.compare_establishments(s):
            if args.produto and args.produto.lower() not in c.product.name.lower():
                continue
            rows.append(f"{c.product.name}: {fmt_brl(c.best.comparable)}/{c.best.comparable_label} em "
                        f"{c.best.quote.establishment.name if c.best.quote.establishment else 's/ estabelecimento'}"
                        f" ({c.best.quote.quoted_on:%d/%m})")
        return "; ".join(rows) or "Nenhum preço cadastrado."
    if name == "consultar_treino_hoje":
        plan = ws.active_plan(s, p.id)
        if not plan:
            return "Sem ficha ativa."
        t = ws.todays_workout(s, p.id, plan)
        if not t.day:
            return "Hoje é dia de descanso na ficha."
        return t.day.title + ": " + "; ".join(
            f"{x.exercise.name_pt or x.exercise.name_original} {x.sets}x{x.reps_min}-{x.reps_max}" for x in t.day.exercises)
    if name == "consultar_cardapio":
        mp = ns.active_plan(s, p.id)
        if not mp:
            return "Sem cardápio ativo."
        sm = ns.summarize(s, mp)
        d = (args.dia or 1) - 1
        meals = sm.days.get(d, [])
        txt = "; ".join(f"{m.meal.meal_type}: " + ", ".join(f"{i.grams:g} g {i.food.short_name or i.food.name}"
                                                             for i in m.meal.items) for m in meals)
        mac = sm.day_macros.get(d)
        return f"Dia {d + 1}: {txt}. Total {mac.kcal:.0f} kcal, {mac.protein:.0f} g proteína." if mac else "Dia inexistente."
    raise ValueError(name)


def prepare_write(s: Session, p: Profile, name: str, args: BaseModel) -> tuple[str, dict]:
    """Valida e resolve a ação proposta. Devolve (descrição para confirmação, argumentos resolvidos)."""
    a = args.model_dump()
    if name == "gerar_treino":
        return "Gerar uma nova ficha de treino a partir do perfil (gerador local, nova versão).", a
    if name == "substituir_exercicio":
        plan = ws.active_plan(s, p.id)
        if not plan:
            raise ValueError("Não há ficha ativa.")
        planned = {(x.exercise.name_pt or x.exercise.name_original).lower(): x for d in plan.days for x in d.exercises}
        cur = _best(args.exercicio_atual, planned)
        new = resolve_library_exercise(s, args.novo_exercicio)
        if not cur:
            raise ValueError(f"'{args.exercicio_atual}' não está na ficha ativa.")
        if not new:
            raise ValueError(f"'{args.novo_exercicio}' não foi encontrado na biblioteca.")
        a.update(planned_id=cur.id, exercise_id=new.id)
        return (f"Trocar {cur.exercise.name_pt or cur.exercise.name_original} por "
                f"{new.name_pt or new.name_original} (cria nova versão da ficha).", a)
    if name == "registrar_treino":
        ex = resolve_library_exercise(s, args.exercicio)
        if not ex:
            raise ValueError(f"'{args.exercicio}' não foi encontrado na biblioteca.")
        a["exercise_id"] = ex.id
        return f"Registrar hoje: {ex.name_pt or ex.name_original}, {args.series}×{args.repeticoes} com {args.carga_kg:g} kg.", a
    if name == "gerar_cardapio":
        e = ps.estimate_energy(p)
        txt = f"Gerar cardápio de {args.dias} dia(s){' econômico' if args.economico else ''} (gerador local) com " \
              f"meta de {e.target_kcal} kcal e {e.protein_g} g de proteína"
        if args.orcamento:
            txt += f", orçamento {fmt_brl(args.orcamento)}"
        return txt + ". O cardápio atual fica no histórico.", a
    if name == "substituir_alimento":
        mp = ns.active_plan(s, p.id)
        if not mp:
            raise ValueError("Não há cardápio ativo.")
        in_plan = {(i.food.short_name or i.food.name).lower(): i.food for m in mp.meals for i in m.items}
        old = _best(args.alimento_atual, in_plan)
        new = resolve_food(s, args.novo_alimento)
        if not old:
            raise ValueError(f"'{args.alimento_atual}' não está no cardápio ativo.")
        if not new:
            raise ValueError(f"'{args.novo_alimento}' não está no catálogo de alimentos.")
        a.update(old_id=old.id, new_id=new.id)
        return (f"Substituir {old.short_name} por {new.short_name} em todo o cardápio, ajustando as gramas para "
                f"manter {'a proteína' if old.group in ns.KEY_NUTRIENT else 'a energia'}.", a)
    if name == "atualizar_preco":
        prod = pr.find_product(s, args.produto)
        if not prod:
            raise ValueError(f"Produto '{args.produto}' não encontrado. Cadastre-o no Mercado Inteligente.")
        a["product_id"] = prod.id
        comp, label = comparable_price(args.preco, args.quantidade, args.unidade)
        return (f"Nova cotação: {prod.name} a {fmt_brl(args.preco)} por {args.quantidade:g} {args.unidade}"
                f" ({fmt_brl(comp)}/{label}){' em ' + args.estabelecimento if args.estabelecimento else ''}.", a)
    if name == "gerar_lista_compras":
        mp = ns.active_plan(s, p.id)
        if not mp:
            raise ValueError("Não há cardápio ativo para gerar a lista.")
        dias = args.dias or mp.days
        return f"Criar lista de compras para {dias} dia(s) do cardápio '{mp.name}', descontando o estoque.", a
    if name == "registrar_peso":
        return f"Registrar peso de hoje: {args.peso_kg:g} kg.", a
    if name == "mudar_treino_hoje":
        plan = ws.active_plan(s, p.id)
        if not plan:
            raise ValueError("Não há ficha ativa.")
        if args.treino.strip().lower() in ("descanso", "folga", "nenhum"):
            a["day_id"] = None
            return "Marcar hoje como descanso.", a
        days = {d.title.lower(): d for d in plan.days}
        days.update({f"treino {chr(65 + i)}".lower(): d for i, d in enumerate(plan.days)})
        days.update({ps.WEEKDAYS[d.weekday].lower(): d for d in plan.days if d.weekday is not None})
        d = _best(args.treino, days, 0.4)
        if not d:
            raise ValueError(f"Treino '{args.treino}' não encontrado na ficha.")
        a["day_id"] = d.id
        return f"Fazer hoje: {d.title}.", a
    raise ValueError(f"ação desconhecida: {name}")


def execute_write(s: Session, p: Profile, name: str, a: dict) -> str:
    if name == "gerar_treino":
        days, warns = ws.local_plan_draft(s, p)
        plan = ws.save_plan(s, p.id, "Ficha gerada pelo chat", days, origin="local", change_note=a.get("pedido"))
        return f"Ficha v{plan.version} criada com {len(days)} dias." + (" " + " ".join(warns) if warns else "")
    if name == "substituir_exercicio":
        plan = ws.active_plan(s, p.id)
        new = ws.replace_exercise(s, plan, a["planned_id"], a["exercise_id"])
        return f"Ficha atualizada para a versão {new.version}."
    if name == "registrar_treino":
        from database.models import SetLog, WorkoutSession
        sess = ws.open_session(s, p.id)
        if not sess:
            plan = ws.active_plan(s, p.id)
            sess = WorkoutSession(profile_id=p.id, plan_id=plan.id if plan else None, performed_on=date.today())
            s.add(sess)
            s.flush()
        start = len([x for x in sess.sets if x.exercise_id == a["exercise_id"]])
        for i in range(a["series"]):
            s.add(SetLog(session_id=sess.id, exercise_id=a["exercise_id"], set_number=start + i + 1,
                         load_kg=a["carga_kg"], reps=a["repeticoes"], completed=True))
        return f"{a['series']} série(s) registradas na sessão de hoje."
    if name == "gerar_cardapio":
        e = ps.estimate_energy(p)
        budget = Decimal(str(a["orcamento"])) if a.get("orcamento") else None
        plan = ns.generate_local_plan(s, p, a["dias"], e.target_kcal, e.protein_g, people=p.people_count or 1,
                                      economic=a["economico"], budget=budget)
        sm = ns.summarize(s, ns.load_plan(s, plan.id))
        return f"Cardápio '{plan.name}' criado. Custo calculado: {fmt_brl(sm.total_cost)}" + (
            f" ({len(sm.unpriced)} itens sem preço cadastrado)." if sm.unpriced else ".")
    if name == "substituir_alimento":
        mp = ns.active_plan(s, p.id)
        n = ns.replace_food_in_plan(s, mp, a["old_id"], a["new_id"])
        return f"{n} item(ns) substituídos; totais recalculados no Plano Alimentar."
    if name == "atualizar_preco":
        pr.add_quote(s, a["product_id"], a["preco"], a["quantidade"], a["unidade"], establishment=a.get("estabelecimento"))
        return "Cotação registrada no histórico de preços."
    if name == "gerar_lista_compras":
        mp = ns.active_plan(s, p.id)
        dias = a.get("dias") or mp.days
        sl = sh.create_list(s, p.id, mp, f"Lista {date.today():%d/%m} ({dias} dias)", day_indexes=set(range(dias)))
        t = sh.totals(sh.load_list(s, sl.id))
        return f"Lista criada com {len(sl.items)} itens, estimativa {fmt_brl(t.estimated)}."
    if name == "registrar_peso":
        ps.record_weight(s, p.id, a["peso_kg"])
        return "Peso registrado."
    if name == "mudar_treino_hoje":
        ws.set_override(s, p.id, date.today(), a["day_id"])
        return "Treino de hoje alterado."
    raise ValueError(name)


# --------------------------------------------------------------------------- conversa

def get_or_create_conversation(s: Session, profile_id: int, conv_id: int | None = None) -> AIConversation:
    if conv_id:
        c = s.get(AIConversation, conv_id)
        if c and c.profile_id == profile_id:
            return c
    c = AIConversation(profile_id=profile_id, title=f"Conversa de {date.today():%d/%m/%Y}")
    s.add(c)
    s.flush()
    return c


def _history_contents(conv: AIConversation):
    from google.genai import types
    out = []
    for m in conv.messages[-HISTORY_LIMIT:]:
        if m.role == "user":
            out.append(types.Content(role="user", parts=[types.Part(text=m.content or "")]))
        elif m.role == "model" and m.content:
            out.append(types.Content(role="model", parts=[types.Part(text=m.content)]))
        elif m.role == "tool":
            status = {"pendente": "aguardando confirmação", "executada": "executada", "recusada": "recusada pelo usuário",
                      "erro": "inválida"}.get(m.tool_status, m.tool_status)
            out.append(types.Content(role="model", parts=[types.Part(
                text=f"[ação {m.tool_name} {status}: {m.content or ''} {m.tool_result or ''}]")]))
    return out


def send_message(s: Session, p: Profile, conv: AIConversation, text: str) -> list[AIMessage]:
    from google.genai import types
    text = (text or "").strip()[:2000]
    if not text:
        return []
    user = AIMessage(conversation_id=conv.id, role="user", content=text)
    s.add(user)
    s.flush()
    s.refresh(conv)
    cfg = types.GenerateContentConfig(system_instruction=SYSTEM_CHAT + "\n\nCONTEXTO ATUAL:\n" + build_context(s, p),
                                      tools=tool_declarations(), temperature=0.4, max_output_tokens=800,
                                      automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    contents = _history_contents(conv)
    resp = gs._call(s, contents=contents, config=cfg, purpose="chat", profile_id=p.id)
    created: list[AIMessage] = []
    calls = list(resp.function_calls or [])
    reply_text = "".join(part.text or "" for c in (resp.candidates or [])[:1] for part in (c.content.parts or [])
                         if getattr(part, "text", None) and not getattr(part, "thought", False))
    read_results = []
    for call in calls[:3]:
        name, raw_args = call.name, dict(call.args or {})
        spec = TOOLS.get(name)
        msg = AIMessage(conversation_id=conv.id, role="tool", tool_name=name, tool_args=raw_args)
        try:
            if not spec:
                raise ValueError("ferramenta inexistente")
            args = spec[0].model_validate(raw_args)
            if spec[1]:
                desc, resolved = prepare_write(s, p, name, args)
                msg.content, msg.tool_args, msg.tool_status = desc, resolved, "pendente"
            else:
                result = _exec_read(s, p, name, args)
                msg.content, msg.tool_result, msg.tool_status = f"Consulta: {name}", result, "executada"
                read_results.append((call, result))
        except (ValidationError, ValueError) as exc:
            msg.content, msg.tool_status = f"Ação '{name}' rejeitada pela validação: {exc}", "erro"
        s.add(msg)
        created.append(msg)
    if read_results and not reply_text.strip():
        # uma segunda chamada apenas quando houve consulta e o modelo ainda não respondeu
        follow = contents + [resp.candidates[0].content] + [types.Content(role="user", parts=[
            types.Part.from_function_response(name=c.name, response={"resultado": r}) for c, r in read_results])]
        resp2 = gs._call(s, contents=follow, config=cfg, purpose="chat", profile_id=p.id)
        reply_text = resp2.text or ""
    if reply_text.strip():
        m = AIMessage(conversation_id=conv.id, role="model", content=reply_text.strip())
        s.add(m)
        created.append(m)
    elif not created:
        m = AIMessage(conversation_id=conv.id, role="model", content="(sem resposta do modelo)")
        s.add(m)
        created.append(m)
    s.flush()
    return created


def confirm_action(s: Session, p: Profile, msg_id: int, approve: bool) -> AIMessage:
    msg = s.get(AIMessage, msg_id)
    if not msg or msg.role != "tool" or msg.tool_status != "pendente" or msg.conversation.profile_id != p.id:
        raise ValueError("Ação não encontrada ou já processada.")
    if not approve:
        msg.tool_status = "recusada"
        return msg
    try:
        msg.tool_result = execute_write(s, p, msg.tool_name, dict(msg.tool_args or {}))
        msg.tool_status = "executada"
    except Exception as exc:  # noqa: BLE001 — erro de negócio exibido ao usuário
        msg.tool_status, msg.tool_result = "erro", str(exc)
    return msg

