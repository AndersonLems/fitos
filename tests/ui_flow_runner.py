"""Integration harness: only invoked by test_ui_flow in an isolated process."""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streamlit.testing.v1 import AppTest
from sqlalchemy import select
from database.connection import run_migrations, session_scope
from database.models import Profile, WorkoutSession
from services import profile_service as ps, seed, workout_service as ws, nutrition_service as ns
from services import backup_service

backup_service.BACKUP_DIR = Path(os.environ['FITOS_UI_TEST_DIR'])
run_migrations()
with session_scope() as s:
    seed.seed_all(s)
    p = ps.create_profile(s, 'Teste visual', 30, 80, 180)
    p.training_weekdays = [date.today().weekday()]
    s.flush()
    pid = p.id

app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30).run()
assert not app.exception, app.exception
with session_scope() as s:
    assert ws.active_plan(s, pid) is None
app.switch_page('views/treinos.py').run()
next(b for b in app.button if b.label == 'Gerar ficha local').click().run()
assert not app.exception, app.exception
app.switch_page('views/dashboard.py').run()
next(b for b in app.button if b.label == 'Começar treino').click().run()
assert not app.exception, app.exception
with session_scope() as s:
    active = ws.open_session(s, pid)
    assert active is not None
    rows = ws.session_sets(s, active.id)
    assert rows
    ws.save_set(s, rows[0].id, pid, load_kg=20, reps=10, completed=True, difficulty='ok')
app.switch_page('views/treinos.py').run()
next(b for b in app.button if b.label == 'Salvar séries').click().run()
assert not app.exception, app.exception
next(b for b in app.button if b.label == 'Finalizar e salvar').click().run()
assert not app.exception, app.exception
with session_scope() as s:
    assert ws.open_session(s, pid) is None
    assert s.scalar(select(WorkoutSession).where(WorkoutSession.profile_id == pid)).finished_at
    prof = s.get(Profile, pid)
    e = ps.estimate_energy(prof)
    ns.generate_local_plan(s, prof, 7, e.target_kcal, e.protein_g)
app.switch_page('views/dashboard.py').run()
assert not app.exception, app.exception
meal_check = next(c for c in app.checkbox if c.key.startswith('dashboard_meal_'))
meal_check.check().run()
assert not app.exception, app.exception
with session_scope() as s:
    consumed, eaten = ns.consumed(s, pid)
    assert consumed.kcal > 0 and len(eaten) == 1
next(c for c in app.checkbox if c.key.startswith('dashboard_meal_') and c.value).uncheck().run()
with session_scope() as s:
    assert not ns.consumed(s, pid)[1]
for page in ['biblioteca', 'plano_alimentar', 'mercado', 'despensa', 'evolucao', 'personal_ia', 'perfil', 'configuracoes']:
    app.switch_page(f'views/{page}.py').run()
    assert not app.exception, (page, app.exception)
# Mercado: produto novo pelo código digitado (sem rede: o Open Food Facts “não conhece” o código).
from decimal import Decimal
from database.models import PriceQuote, Product, ShoppingList
from services import product_scan, shopping_service as sh
product_scan._off_cache['7891000100103'] = None
with session_scope() as s:
    quick = sh.create_quick_list(s, pid, 'Compra de teste', 50).id
app.session_state['scan_lista'] = quick
app.switch_page('views/mercado.py').run()
next(r for r in app.radio if r.key == 'scan_modo').set_value('Digitar código').run()
next(t for t in app.text_input if t.key == 'scan_txt0').input('7891000100103').run()
assert not app.exception, app.exception
next(t for t in app.text_input if t.label == 'Nome').input('Arroz integral teste')
next(t for t in app.text_input if t.label == 'Preço da embalagem (R$)').input('8,90')
next(b for b in app.button if b.label == 'Cadastrar e salvar preço').click().run()
assert not app.exception, app.exception
with session_scope() as s:
    prod = s.scalar(select(Product).where(Product.barcode == '7891000100103'))
    assert prod is not None and prod.name == 'Arroz integral teste'
    assert s.scalar(select(PriceQuote).where(PriceQuote.product_id == prod.id)).price == Decimal('8.90')
    assert sh.totals(sh.load_list(s, quick)).paid == Decimal('8.90')
next(n for n in app.number_input if n.key == f'orc_lista{quick}').set_value(80.0).run()
assert not app.exception, app.exception
with session_scope() as s:
    assert s.get(ShoppingList, quick).budget == 80
# Tema por perfil
app.switch_page('views/perfil.py').run()
next(r for r in app.radio if r.label == 'Tema deste perfil').set_value('brasa').run()
assert not app.exception, app.exception
with session_scope() as s:
    assert s.get(Profile, pid).theme == 'brasa'
assert app.session_state['tema'] == 'brasa'
# Prazo da meta: cálculo local, escolha do cenário e análise (IA simulada, sem rede)
from database.models import GoalPlan
from services import gemini_service as gs_mod, goal_service as gls
with session_scope() as s:
    s.get(Profile, pid).target_weight_kg = 74
app.switch_page('views/evolucao.py').run()
next(b for b in app.button if b.label == 'Calcular prazos').click().run()
assert not app.exception, app.exception
with session_scope() as s:
    gp = gls.active(s, pid)
    assert gp and gp.chosen == 'conservador' and len(gp.scenarios) == 3
next(r for r in app.radio if r.label == 'Cenário que vale para os cardápios').set_value('intenso').run()
assert not app.exception, app.exception
with session_scope() as s:
    gp = gls.active(s, pid)
    assert gp.chosen == 'intenso'
    intenso = gls.chosen_scenario(gp)
app.switch_page('views/plano_alimentar.py').run()
assert not app.exception, app.exception
assert any(n.value == intenso.kcal for n in app.number_input if n.label.startswith('Meta diária'))
gs_mod.is_configured = lambda: True
gs_mod.generate_structured = lambda *a, **k: gs_mod.GGoalReview(
    analysis='Ritmo **moderado** é realista.', recommended='rapido',
    scenarios=[gs_mod.GGoalScenario(key=k_, kcal_adjust=0, meals_per_day=5, tips='Dica.') for k_ in gls.KEYS])
app.switch_page('views/evolucao.py').run()
next(b for b in app.button if b.label == 'Analisar com IA').click().run()
assert not app.exception, app.exception
with session_scope() as s:
    gp = gls.active(s, pid)
    assert gp.chosen == 'rapido' and gp.analysis.startswith('Ritmo') and gls.chosen_scenario(gp).meals_per_day == 5
    assert s.query(GoalPlan).filter(GoalPlan.profile_id == pid).count() == 2
app.switch_page('views/dashboard.py').run()
assert not app.exception, app.exception
print('All ten pages and workout/meal persistence passed.')
