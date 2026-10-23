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
print('All ten pages and workout/meal persistence passed.')
