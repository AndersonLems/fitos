import streamlit as st
from sqlalchemy import func, select

from components import ui
from components.state import require_profile
from database.connection import session_scope
from database.models import AIConversation, AIMessage, AIUsage, Profile
from services import chat_service as cs
from services import gemini_service as gs

p = require_profile()
ui.page_header("Meu personal IA", "Converse sobre treino, cardápio, compras e preços. O assistente conhece seu perfil, "
               "a ficha, o cardápio, a despensa e os preços; quando propõe uma alteração, nada muda sem a sua "
               "confirmação.", kicker="Gemini")

if not gs.is_configured():
    st.warning("Configure GEMINI_API_KEY no arquivo .env para usar o chat.")
    st.stop()

with session_scope() as s:
    convs = list(s.scalars(select(AIConversation).where(AIConversation.profile_id == p.id)
                           .order_by(AIConversation.id.desc())))
    tokens = s.execute(select(func.coalesce(func.sum(AIUsage.input_tokens), 0),
                              func.coalesce(func.sum(AIUsage.output_tokens), 0), func.count(AIUsage.id))
                       .where(AIUsage.profile_id == p.id)).one()

with st.sidebar:
    st.markdown("**Conversas**")
    if st.button("Nova conversa", width="stretch"):
        st.session_state.pop("conv_id", None)
        st.rerun()
    for c in convs[:12]:
        if st.button(c.title, key=f"c{c.id}", width="stretch",
                     type="primary" if c.id == st.session_state.get("conv_id") else "secondary"):
            st.session_state["conv_id"] = c.id
            st.rerun()

conv_id = st.session_state.get("conv_id")
msgs = []
if conv_id:
    with session_scope() as s:
        conv = s.get(AIConversation, conv_id)
        if conv and conv.profile_id == p.id:
            msgs = [(m.id, m.role, m.content, m.tool_name, m.tool_status, m.tool_result) for m in conv.messages]
        else:
            st.session_state.pop("conv_id", None)

if not msgs:
    ui.note("Exemplos: “Monte meu treino de amanhã” · “Quero trocar supino reto por outro exercício” · "
            "“Meu frango agora custa R$ 23,90 o quilo” · “Quantos quilos de arroz preciso comprar este mês?” · "
            "“Estou com dificuldade de completar minhas séries.”")

STATUS = {"pendente": ("aguardando sua confirmação", "warn"), "executada": ("executada", "ok"),
          "recusada": ("recusada", ""), "erro": ("não executada", "bad")}
for mid, role, content, tool, status, result in msgs:
    if role == "user":
        with st.chat_message("user"):
            st.markdown(content)
    elif role == "model":
        with st.chat_message("assistant"):
            st.markdown(content)
    else:
        with st.chat_message("assistant"):
            label, kind = STATUS.get(status, (status, ""))
            st.html(f'<div class="fx-card" style="margin:0"><h3>Ação: {ui.esc(tool)}</h3><p>{ui.esc(content)}</p>'
                    f'{ui.chip(label, kind)}'
                    + (f'<p class="fx-note">{ui.esc(result)}</p>' if result and tool and not tool.startswith("consultar")
                       else "") + "</div>")
            if status == "pendente":
                c1, c2, _ = st.columns([1, 1, 4])
                if c1.button("Confirmar", key=f"ok{mid}", type="primary"):
                    with session_scope() as s:
                        cs.confirm_action(s, s.get(Profile, p.id), mid, True)
                    st.rerun()
                if c2.button("Recusar", key=f"no{mid}"):
                    with session_scope() as s:
                        cs.confirm_action(s, s.get(Profile, p.id), mid, False)
                    st.rerun()

prompt = st.chat_input("Escreva sua mensagem")
if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)
    try:
        with ui.loading("Pensando…"), session_scope() as s:
            conv = cs.get_or_create_conversation(s, p.id, st.session_state.get("conv_id"))
            if not conv.messages:
                conv.title = prompt[:60]
            st.session_state["conv_id"] = conv.id
            cs.send_message(s, s.get(Profile, p.id), conv, prompt)
        st.rerun()
    except gs.GeminiUnavailable as exc:
        st.error(str(exc))

ui.note(f"Uso deste perfil: {tokens[2]} chamadas, {tokens[0]:,} tokens de entrada e {tokens[1]:,} de saída."
        .replace(",", ".") + " O histórico enviado ao modelo é limitado às últimas mensagens para economizar tokens.")
