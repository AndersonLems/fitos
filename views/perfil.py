from decimal import Decimal

import streamlit as st

from components import ui
from components import auth
from components.state import flash, require_profile
from config.settings import ACCESS_CODE
from database.connection import session_scope
from database.models import Profile
from services import auth_service as auth_svc
from services import profile_service as ps
from services.backup_service import delete_profile
from services.catalog_data import EQUIPMENT_CHOICES

p = require_profile()
ui.page_header("Meu perfil", "Só idade, peso e altura são obrigatórios. Cada dado opcional deixa as estimativas "
               "e as sugestões mais adequadas; nada é presumido sem aviso.")

initials = "".join(part[0] for part in p.name.split()[:2])
st.html(f'<div class="fx-profile"><span>{ui.esc(initials)}</span><div><strong>{ui.esc(p.name)}</strong>'
        f'<p>{ui.esc(ps.GOALS.get(p.goal, "Objetivo não informado"))} · '
        f'{ui.esc(ps.EXPERIENCE.get(p.experience, "Experiência não informada"))}</p></div></div>')

e = ps.estimate_energy(p)
missing = ps.missing_for_personalization(p)
ui.tiles([
    {"label": "Gasto basal estimado", "value": f"{ui.fmt_num(e.bmr)} kcal", "provisional": p.sex not in ("M", "F")},
    {"label": "Gasto diário estimado", "value": f"{ui.fmt_num(e.tdee)} kcal", "provisional": not p.activity_level},
    {"label": "Meta para o objetivo", "value": f"{ui.fmt_num(e.target_kcal)} kcal", "provisional": e.is_provisional,
     "detail": f"faixa {e.range_kcal[0]}–{e.range_kcal[1]} kcal sem o dado de sexo" if e.range_kcal else ""},
    {"label": "Proteína / gordura / carboidrato", "value": f"{e.protein_g} / {e.fat_g} / {e.carbs_g} g"},
])
if missing:
    ui.note("Para personalizar melhor, informe: " + ", ".join(missing) + ".")
for n in e.notes:
    ui.note(n)

opt = lambda d: [None, *d]  # noqa: E731
with st.form("perfil"):
    st.subheader("Dados básicos")
    c1, c2, c3, c4 = st.columns(4)
    name = c1.text_input("Nome", p.name)
    age = c2.number_input("Idade", 12, 100, p.age)
    weight = c3.number_input("Peso atual (kg)", 30.0, 300.0, float(p.weight_kg), 0.1, format="%.1f",
                             help="Alterar aqui também registra uma pesagem de hoje.")
    height = c4.number_input("Altura (cm)", 120.0, 230.0, float(p.height_cm), 0.5, format="%.1f")

    st.subheader("Objetivo e rotina")
    c1, c2, c3 = st.columns(3)
    sex = c1.selectbox("Sexo para estimativas fisiológicas", opt(["F", "M"]), index=opt(["F", "M"]).index(p.sex),
                       format_func=lambda v: {"F": "Feminino", "M": "Masculino", None: "Não informar"}[v])
    goal = c2.selectbox("Objetivo", opt(list(ps.GOALS)), index=opt(list(ps.GOALS)).index(p.goal),
                        format_func=lambda v: ps.GOALS.get(v, "Não informado"))
    target = c3.number_input("Meta de peso (kg)", 30.0, 300.0, p.target_weight_kg, 0.5, format="%.1f")
    c1, c2, c3 = st.columns(3)
    act = c1.selectbox("Nível de atividade", opt(list(ps.ACTIVITY)), index=opt(list(ps.ACTIVITY)).index(p.activity_level),
                       format_func=lambda v: ps.ACTIVITY[v][1] if v else "Não informado")
    exp = c2.selectbox("Experiência de treino", opt(list(ps.EXPERIENCE)), index=opt(list(ps.EXPERIENCE)).index(p.experience),
                       format_func=lambda v: ps.EXPERIENCE.get(v, "Não informada"))
    minutes = c3.number_input("Tempo por treino (min)", 20, 180, p.session_minutes, 5)
    days = st.multiselect("Dias disponíveis para academia", list(range(7)), p.training_weekdays or [],
                          format_func=lambda i: ps.WEEKDAYS[i])
    equipment = st.multiselect("Equipamentos disponíveis", EQUIPMENT_CHOICES,
                               [x for x in (p.equipment or []) if x in EQUIPMENT_CHOICES])
    injuries = st.text_area("Lesões ou limitações físicas", p.injuries or "",
                            placeholder="Ex.: dor no joelho direito ao agachar fundo")

    st.subheader("Alimentação")
    c1, c2 = st.columns(2)
    restrictions = c1.text_area("Restrições alimentares", p.restrictions or "", placeholder="Ex.: sem lactose, vegetariano")
    allergies = c2.text_area("Alergias", p.allergies or "", placeholder="Ex.: amendoim")
    prefs = st.text_area("Preferências", p.preferences or "",
                         placeholder="Ex.: prefiro refeições rápidas; não como beterraba")
    c1, c2 = st.columns(2)
    budget = c1.number_input("Orçamento mensal fixo para alimentação (R$)", 0.0, 100000.0,
                             float(p.monthly_food_budget) if p.monthly_food_budget else None, 10.0, format="%.2f",
                             help="Vale para todo mês sem valor próprio. Para um mês diferente, ajuste em "
                                  "Mercado inteligente › Gastos; para uma compra, na lista de compras.")
    people = c2.number_input("Pessoas no planejamento alimentar", 1, 12, p.people_count or 1)
    ui.note("Restrições, alergias e preferências são aplicadas por palavras-chave aos cardápios gerados "
            "(ex.: “lactose”, “vegetariano”, “glúten”, “amendoim”, nome de um alimento). Confira sempre o resultado.")
    saved = st.form_submit_button("Salvar perfil", type="primary")

if saved:
    try:
        ps.validate_basics(age, weight, height)
        with session_scope() as s:
            obj = s.get(Profile, p.id)
            if abs(weight - obj.weight_kg) >= 0.05:
                ps.record_weight(s, p.id, weight, notes="Atualizado no perfil")
            obj.name = (name or obj.name).strip()[:80]
            obj.age, obj.weight_kg, obj.height_cm = int(age), float(weight), float(height)
            obj.sex, obj.goal, obj.target_weight_kg = sex, goal, target
            obj.activity_level, obj.experience, obj.session_minutes = act, exp, minutes
            obj.training_weekdays = sorted(days) or None
            obj.equipment = equipment or None
            obj.injuries, obj.restrictions = injuries.strip() or None, restrictions.strip() or None
            obj.allergies, obj.preferences = allergies.strip() or None, prefs.strip() or None
            obj.monthly_food_budget = Decimal(str(round(budget, 2))) if budget else None
            obj.people_count = int(people)
        flash("Perfil salvo.")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))

st.subheader("Tema de cores")
st.html('<div class="fx-tiles">' + "".join(ui.theme_swatch_html(k) for k in ui.THEMES) + "</div>")
choice = st.radio("Tema deste perfil", list(ui.THEMES), index=list(ui.THEMES).index(ui.theme_key()),
                  format_func=lambda k: ui.THEMES[k]["label"], horizontal=True,
                  help="Vale só para este perfil, em todos os aparelhos.")
if choice != ui.theme_key():
    with session_scope() as s:
        s.get(Profile, p.id).theme = choice
    ui.set_theme(choice)
    flash(f"Tema “{ui.THEMES[choice]['label']}” aplicado.")
    st.rerun()

with st.expander("Código de acesso", expanded=p.access_hash is None):
    if p.access_hash is None:
        st.warning("Este perfil ainda entra com o código da instalação. Defina um código só dele.")
    with st.form("codigo", clear_on_submit=True):
        current = st.text_input("Código atual" if p.access_hash else "Código da instalação", type="password",
                                disabled=p.access_hash is None and not ACCESS_CODE)
        c1, c2 = st.columns(2)
        new = c1.text_input("Novo código", type="password",
                            help=f"De {auth_svc.MIN_LEN} a {auth_svc.MAX_LEN} caracteres.")
        new2 = c2.text_input("Repita o novo código", type="password")
        ok = st.form_submit_button("Salvar código", type="primary")
    ui.note("Trocar o código encerra a entrada lembrada nos outros aparelhos deste perfil.")
    if ok:
        try:
            if not auth_svc.can_enter(p.access_hash, current, ACCESS_CODE):
                raise ValueError("Código atual incorreto.")
            code = auth_svc.validate_new_code(new)
            if code != new2.strip():
                raise ValueError("Os dois códigos não são iguais.")
            with session_scope() as s:
                obj = s.get(Profile, p.id)
                obj.access_hash = auth_svc.hash_code(code)
                h = obj.access_hash
            auth.refresh_cookie(p.id, h)
            flash("Código de acesso salvo.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

with st.expander("Apagar este perfil"):
    st.write("Remove o perfil e todos os dados dele: medidas, treinos, cardápios, despensa, listas, compras e "
             "conversas. Um backup do banco é feito antes. Preços e produtos cadastrados são mantidos.")
    confirm = st.text_input(f"Digite o nome do perfil ({p.name}) para confirmar")
    if st.button("Apagar perfil definitivamente", type="secondary", disabled=confirm.strip() != p.name):
        with session_scope() as s:
            delete_profile(s, p.id)
        auth.logout()
        st.rerun()
