"""Fluxo de entrada por perfil no app real (AppTest); chamado só por test_auth em processo isolado."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streamlit.testing.v1 import AppTest

from database.connection import run_migrations, session_scope
from services import auth_service as auth, backup_service, profile_service as ps, seed

backup_service.BACKUP_DIR = Path(os.environ["FITOS_UI_TEST_DIR"])
run_migrations()
with session_scope() as s:
    seed.seed_all(s, allow_network=False)
    ana = ps.create_profile(s, "Ana", 30, 60, 165)
    ana.access_hash = auth.hash_code("ana-123")
    ps.create_profile(s, "Bruno", 35, 80, 180)  # perfil antigo, sem código próprio
    ana_id = ana.id

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def logged(app):
    try:
        return app.session_state["profile_id"]
    except KeyError:
        return None


def enter(app, name, code):
    # campos de formulário só são enviados junto com o botão do formulário
    app.selectbox[0].select(next(o for o in app.selectbox[0].options if o == name))
    app.text_input[0].input(code)
    next(b for b in app.button if b.label == "Entrar").click().run()


app = AppTest.from_file(APP, default_timeout=30).run()
assert not app.exception, app.exception
assert any(b.label == "Entrar" for b in app.button), "tela de entrada não apareceu"

enter(app, "Ana", "instalacao")  # o código da instalação não abre perfil com código próprio
assert logged(app) is None and any("incorreto" in e.value for e in app.error)

enter(app, "Ana", "ana-123")
assert not app.exception, app.exception
assert logged(app) == ana_id

# Sessão nova (outro navegador): começa na tela de entrada.
app = AppTest.from_file(APP, default_timeout=30).run()
assert logged(app) is None and any(b.label == "Entrar" for b in app.button)
enter(app, "Bruno", "instalacao")  # perfil antigo entra com o código da instalação
assert logged(app) not in (None, ana_id) and not app.exception
print("Entrada por perfil verificada.")
