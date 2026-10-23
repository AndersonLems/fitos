from datetime import datetime

import pandas as pd
import streamlit as st
from sqlalchemy import func, select

from components import ui
from components.state import flash, require_profile
from config.settings import ACCESS_CODE, GROQ_MODEL_DEFAULT, gemini_api_key, groq_api_key
from database.connection import session_scope
from database.models import AIUsage, Setting
from services import backup_service as bk
from services import gemini_service as gs

p = require_profile()
ui.page_header("Configurações", "Gemini, backups, exportação e exclusão de dados.")

with ui.panel("gemini"):
    st.subheader("IA — Gemini com GroqCloud de reserva")
    st.caption(f"Gemini é o padrão. Em caso de falha, tenta GroqCloud ({GROQ_MODEL_DEFAULT}). "
               f"Chave GroqCloud: {'configurada' if groq_api_key() else 'ausente'}.")
    key = gemini_api_key()
    with session_scope() as s:
        model = gs.current_model(s)
        usage = s.execute(select(AIUsage.purpose, func.count(AIUsage.id), func.sum(AIUsage.input_tokens),
                                 func.sum(AIUsage.output_tokens)).group_by(AIUsage.purpose)).all()
    c1, c2 = st.columns(2)
    c1.markdown(f"Chave: **{'configurada' if key else 'ausente'}**"
                + (f" (termina em …{key[-4:]})" if key else "") + "  \nA chave fica apenas no arquivo `.env`.")
    opts = list(dict.fromkeys([model, *gs.MODEL_CHOICES]))
    new_model = c2.selectbox("Modelo", opts, index=0, help="Modelos “lite” gastam menos; nomes mudam com o tempo.")
    if new_model != model:
        with session_scope() as s:
            st_ = s.get(Setting, "gemini_model") or Setting(key="gemini_model")
            st_.value = new_model
            s.merge(st_)
        flash(f"Modelo alterado para {new_model}.")
        st.rerun()
    if st.button("Verificar conexão (não consome tokens)", disabled=not key):
        try:
            info = gs.client().models.get(model=model)
            st.success(f"Conectado. Modelo disponível: {info.display_name or info.name}.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Falha: {type(exc).__name__}. Verifique chave e nome do modelo.")
    if usage:
        st.dataframe(pd.DataFrame([{"uso": u[0], "chamadas": u[1], "tokens entrada": u[2] or 0, "tokens saída": u[3] or 0}
                                   for u in usage]), hide_index=True, width="stretch")
    ui.note("O FitOS só chama a IA quando você clica em um botão de geração ou envia mensagem no chat. "
            "Gerador local de fichas e cardápios, cálculos, custos e listas não usam IA.")

with ui.panel("acesso"):
    st.subheader("Acesso")
    st.markdown(("Código de acesso **ativo** (FITOS_ACCESS_CODE no `.env`)." if ACCESS_CODE else
                 "Sem código de acesso. Não exponha o app pela internet assim.")
                + " Para trocar o código, edite o `.env` e reinicie o serviço.")

with ui.panel("backup"):
    st.subheader("Backup")
    c1, c2 = st.columns([1, 3])
    if c1.button("Fazer backup agora", type="primary"):
        path = bk.backup_now()
        flash(f"Backup criado: {path.name}")
        st.rerun()
    backups = bk.list_backups()
    c2.caption(f"Backups automáticos diários ao abrir o app; os 20 mais recentes são mantidos em `backups/`. "
               f"{len(backups)} disponível(is).")
    if backups:
        b = st.selectbox("Baixar backup", backups, format_func=lambda x: f"{x.name} · "
                         f"{datetime.fromtimestamp(x.stat().st_mtime):%d/%m/%Y %H:%M} · {x.stat().st_size / 1e6:.1f} MB")
        st.download_button("Baixar arquivo .db", b.read_bytes(), file_name=b.name, mime="application/x-sqlite3")
        ui.note("Para restaurar: pare o serviço, substitua <code>data/fitos.db</code> pelo arquivo do backup e reinicie.")

with ui.panel("exportar"):
    st.subheader("Exportar dados")
    c1, c2, c3 = st.columns(3)
    scope = c1.radio("Escopo", ["Este perfil", "Instalação inteira"])
    fmt = c2.radio("Formato", ["csv", "json"])
    data = bk.export_zip(p.id if scope == "Este perfil" else None, fmt)
    c3.download_button("Baixar exportação (.zip)", data, file_name=f"fitos-{fmt}-{datetime.now():%Y%m%d}.zip",
                       mime="application/zip")

with ui.panel("apagar"):
    st.subheader("Apagar dados deste perfil")
    SECTIONS = {"measurements": "Medidas e pesagens", "workout_sessions": "Sessões e séries de treino",
                "workout_plans": "Fichas de treino (todas as versões)", "meal_plans": "Cardápios",
                "meal_logs": "Refeições marcadas como consumidas", "inventory_items": "Despensa",
                "shopping_lists": "Listas de compras", "purchases": "Histórico de compras",
                "ai_conversations": "Conversas com a IA", "ai_insights": "Textos gerados pela IA"}
    sec = st.selectbox("O que apagar", list(SECTIONS), format_func=SECTIONS.get)
    confirm = st.text_input("Digite APAGAR para confirmar")
    if st.button("Apagar", disabled=confirm.strip() != "APAGAR"):
        with session_scope() as s:
            n = bk.delete_profile_section(s, p.id, sec)
        flash(f"{n} registro(s) apagados ({SECTIONS[sec]}). Backup feito antes.")
        st.rerun()
    ui.note("Para apagar o perfil inteiro, use Meu perfil → Apagar este perfil.")

with ui.panel("fontes"):
    st.subheader("Fontes e limitações")
    st.html(ui.bullet_list([
        "Composição dos alimentos: TACO 4ª ed. (NEPA/UNICAMP, 2011), via conjunto normalizado do projeto taco-api.",
        "Índice de cocção e fator de correção: valores de referência de técnica dietética, aproximados e editáveis.",
        "Energia: equação de Mifflin-St Jeor com fatores de atividade usuais — estimativa populacional.",
        "Exercícios: ExerciseDB (versão aberta, mídias referenciadas sem cópia local) e wger (CC-BY-SA).",
        "WorkoutDB: sem API pública acessível na avaliação; integração não implementada.",
        "Preços: somente os cadastrados por você; não há coleta automática de preços de mercados.",
        "Restrições alimentares são aplicadas por palavras-chave; confira os cardápios gerados.",
    ]))
