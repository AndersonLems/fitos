from datetime import date
from decimal import Decimal

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select

from components import scan_view, ui
from components.state import flash, require_profile
from database.connection import session_scope
from database.models import Establishment, Food, PriceQuote, Product, ShoppingItem, ShoppingList
from services import nutrition_service as ns
from services import budget_service as bs
from services import pricing_service as pr
from services import product_scan as scan
from services import shopping_service as sh
from services.insights import month_spending
from utils.units import UNIT_LABELS, UnitError, comparable_price, fmt_brl, fmt_qty, money

p = require_profile()
ui.page_header("Mercado inteligente", "Seus preços locais, normalizados por kg, litro ou unidade. Eles alimentam o "
               "custo dos cardápios, a versão econômica e a lista de compras. Não há preços em tempo real: vale o "
               "que você cadastrar.")

tabs = st.tabs(["Escanear produto", "Preços", "Comparar mercados", "Histórico de preços", "Lista de compras", "Custos do cardápio",
                "Gastos"])

# ============================================================================ ESCANEAR
with tabs[0]:
    scan_view.render(p)

# ============================================================================ PREÇOS
with tabs[1]:
    with session_scope() as s:
        products = list(s.scalars(select(Product).order_by(Product.name)))
        ests = [e.name for e in s.scalars(select(Establishment).order_by(Establishment.name))]
        latest = pr.latest_quotes(s)
        n_quotes = s.query(PriceQuote).count()
    prod_names = {x.id: x.name + (f" ({x.brand})" if x.brand else "") for x in products}

    with st.expander("Cadastrar preço", icon=":material/add:"):
        with st.form("cotacao", clear_on_submit=True):
            st.markdown("**Cadastrar preço**")
            c1, c2, c3, c4 = st.columns([3, 1.3, 1.2, 1.2])
            pid = c1.selectbox("Produto", list(prod_names), format_func=prod_names.get, index=None,
                               placeholder="Escolha o produto")
            price = c2.text_input("Preço (R$)", placeholder="19,90")
            qty = c3.text_input("Quantidade da embalagem", value="1")
            unit = c4.selectbox("Unidade", list(UNIT_LABELS), format_func=UNIT_LABELS.get)
            c1, c2, c3 = st.columns([2, 1, 3])
            est = c1.selectbox("Estabelecimento", [*ests, "+ novo"], index=None, placeholder="Opcional")
            new_est = c1.text_input("Nome do novo estabelecimento", label_visibility="collapsed",
                                    placeholder="Novo estabelecimento (se escolheu “+ novo”)")
            qdate = c2.date_input("Data da cotação", date.today(), format="DD/MM/YYYY")
            notes = c3.text_input("Observações", placeholder="Ex.: promoção até sexta")
            ui.note("Pacotes: informe o conteúdo do pacote — ex.: arroz 5 kg → quantidade 5, unidade kg; "
                    "ovos em dúzia → 1 dúzia; aveia 500 g → 500 g.")
            ok = st.form_submit_button("Salvar preço", type="primary")
    if ok:
        try:
            if pid is None:
                raise UnitError("Escolha o produto.")
            with session_scope() as s:
                q = pr.add_quote(s, pid, price, qty, unit, quoted_on=qdate, notes=notes or None,
                                 establishment=new_est if est == "+ novo" else est)
                comp, label = comparable_price(q.price, q.package_qty, q.unit)
            flash(f"Preço salvo: {prod_names[pid]} = {fmt_brl(comp)}/{label}.")
            st.rerun()
        except UnitError as exc:
            st.error(str(exc))

    if latest:
        best = {}
        for v in latest:
            if v.product.id not in best or v.comparable < best[v.product.id].comparable:
                best[v.product.id] = v
        rows = [{"produto": prod_names.get(v.product.id, v.product.name), "categoria": v.product.category,
                 "melhor preço": f"{fmt_brl(v.comparable)}/{v.comparable_label}",
                 "embalagem": f"{fmt_brl(v.quote.price)} · {pr.base_qty_label(v.quote.package_qty, v.quote.unit)}",
                 "estabelecimento": v.quote.establishment.name if v.quote.establishment else "—",
                 "cotação": ui.fmt_date(v.quote.quoted_on),
                 "alimento ligado": v.product.food.short_name or v.product.food.name if v.product.food else "—"}
                for v in best.values()]
        st.dataframe(pd.DataFrame(rows).sort_values("produto"), hide_index=True, width="stretch")
    else:
        st.info("Nenhum preço cadastrado ainda.")
    missing = [x.name for x in products if x.id not in {v.product.id for v in latest}]
    if missing:
        ui.note("Produtos sem preço: " + ui.esc(", ".join(missing)))

    with st.expander("Cadastrar ou editar produto"):
        with session_scope() as s:
            foods = list(s.scalars(select(Food).order_by(Food.is_core.desc(), Food.short_name, Food.name)))
        fmap = {f.id: (f.short_name or f.name) + ("" if f.short_name else f" (TACO)") for f in foods}
        editing = st.selectbox("Produto", [None, *prod_names], format_func=lambda i: "Novo produto" if i is None
                               else prod_names[i])
        cur = next((x for x in products if x.id == editing), None)
        with st.form("produto"):
            c1, c2, c3 = st.columns([3, 2, 2])
            name = c1.text_input("Nome", cur.name if cur else "")
            cat = c2.text_input("Categoria", cur.category if cur and cur.category else "",
                                placeholder="Carnes, Hortifrúti…")
            brand = c3.text_input("Marca (opcional)", cur.brand if cur and cur.brand else "")
            food_id = st.selectbox("Alimento que este produto fornece (para custo e nutrição)", [None, *fmap],
                                   index=([None, *fmap].index(cur.food_id) if cur and cur.food_id in fmap else 0),
                                   format_func=lambda i: "— sem vínculo —" if i is None else fmap[i])
            c1, c2 = st.columns(2)
            gpu = c1.number_input("Peso médio por unidade (g) — itens vendidos por unidade", 0.0, 5000.0,
                                  cur.grams_per_unit if cur and cur.grams_per_unit else None, 1.0)
            dens = c2.number_input("Densidade (g/ml) — líquidos", 0.3, 2.0,
                                   cur.density_g_ml if cur and cur.density_g_ml else None, 0.01)
            c1, c2 = st.columns([1, 2])
            pbarcode = c1.text_input("Código de barras (opcional)", cur.barcode if cur and cur.barcode else "",
                                     placeholder="7891234567895")
            pnotes = c2.text_input("Observações", cur.notes if cur and cur.notes else "")
            save = st.form_submit_button("Salvar produto")
        if save:
            try:
                code = scan.normalize_barcode(pbarcode)
                if pbarcode.strip() and not code:
                    raise UnitError("Código de barras inválido (confira os dígitos).")
                with session_scope() as s:
                    other = scan.find_by_barcode(s, code) if code else None
                    if other and (not cur or other.id != cur.id):
                        raise UnitError(f"O código {code} já pertence a “{other.name}”.")
                    if cur:
                        obj = s.get(Product, cur.id)
                        obj.barcode = code
                        obj.name, obj.category, obj.brand = name.strip() or obj.name, cat or None, brand or None
                        obj.food_id, obj.grams_per_unit, obj.density_g_ml = food_id, gpu or None, dens or None
                        obj.notes = pnotes or None
                    else:
                        pr.create_product(s, name, food_id, category=cat or None, brand=brand, grams_per_unit=gpu,
                                          density_g_ml=dens, notes=pnotes, barcode=code)
                flash("Produto salvo.")
                st.rerun()
            except UnitError as exc:
                st.error(str(exc))
        if cur:
            if st.checkbox(f"Quero apagar “{cur.name}” e todo o histórico de preços dele"):
                if st.button("Apagar produto"):
                    with session_scope() as s:
                        s.delete(s.get(Product, cur.id))
                    st.rerun()

    if n_quotes == 0:
        with st.expander("Carregar preços de exemplo (fictícios)"):
            st.write("Insere os valores de exemplo do enunciado com o estabelecimento “Exemplo (fictício)”, apenas para "
                     "testar o fluxo. Apague ou substitua pelos seus preços reais.")
            if st.button("Carregar exemplo"):
                sample = [("Peito de frango (filé)", "19,90", 1, "kg"), ("Patinho", "32,90", 1, "kg"),
                          ("Arroz branco tipo 1", "5,50", 1, "kg"), ("Feijão carioca", "8,90", 1, "kg"),
                          ("Ovo branco", "0,80", 1, "un"), ("Banana prata", "5,90", 1, "kg"),
                          ("Aveia em flocos", "12,90", 1, "kg"), ("Leite integral", "5,50", 1, "l")]
                with session_scope() as s:
                    by = {x.name: x.id for x in s.scalars(select(Product))}
                    for n, v, q, u in sample:
                        if n in by:
                            pr.add_quote(s, by[n], v, q, u, establishment="Exemplo (fictício)",
                                         notes="valor fictício de exemplo")
                st.rerun()

# ============================================================================ COMPARAR
with tabs[2]:
    with session_scope() as s:
        comps = pr.compare_establishments(s)
    multi = [c for c in comps if len(c.rows) > 1]
    if not comps:
        st.info("Cadastre preços para comparar.")
    else:
        rows = []
        for c in comps:
            rows.append({"produto": c.product.name,
                         "menor preço": f"{fmt_brl(c.best.comparable)}/{c.best.comparable_label}",
                         "onde": c.best.quote.establishment.name if c.best.quote.establishment else "—",
                         "maior preço": f"{fmt_brl(c.worst.comparable)}/{c.worst.comparable_label}" if len(c.rows) > 1 else "—",
                         "diferença": f"{c.spread_pct:.1f}%".replace(".", ",") if len(c.rows) > 1 else "—",
                         "última cotação": ui.fmt_date(max(r.quote.quoted_on for r in c.rows)),
                         "mercados": len(c.rows)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        ui.note("Comparação com a cotação mais recente de cada produto em cada estabelecimento.")

    with session_scope() as s:
        open_list = s.scalar(select(ShoppingList).where(ShoppingList.profile_id == p.id,
                                                        ShoppingList.status == "aberta")
                             .order_by(ShoppingList.id.desc()).limit(1))
        if open_list and multi:
            sl = sh.load_list(s, open_list.id)
            lv = pr.latest_quotes(s)
            by_est: dict[str, Decimal] = {}
            cover: dict[str, int] = {}
            needed = [it for it in sl.items if it.food_id]
            for est_name in {v.quote.establishment.name for v in lv if v.quote.establishment}:
                tot, n = Decimal(0), 0
                for it in needed:
                    opts = [v for v in lv if v.product.food_id == it.food_id and v.quote.establishment
                            and v.quote.establishment.name == est_name and v.per_gram]
                    if opts:
                        tot += min(v.per_gram for v in opts) * it.to_buy_base
                        n += 1
                by_est[est_name], cover[est_name] = money(tot), n
            st.markdown(f"**Lista “{sl.name}” por estabelecimento** (custo proporcional, sem arredondar embalagens)")
            st.dataframe(pd.DataFrame([{"estabelecimento": k, "itens com preço": f"{cover[k]} de {len(needed)}",
                                        "custo": fmt_brl(v)} for k, v in sorted(by_est.items(), key=lambda x: x[1])]),
                         hide_index=True, width="stretch")
            full = {k: v for k, v in by_est.items() if cover[k] == len(needed)}
            if len(full) >= 2:
                lo, hi = min(full.values()), max(full.values())
                st.success(f"Economia potencial escolhendo o mercado mais barato para a lista toda: {fmt_brl(hi - lo)}.")

# ============================================================================ HISTÓRICO
with tabs[3]:
    with session_scope() as s:
        quoted = list(s.scalars(select(Product).where(Product.quotes.any()).order_by(Product.name)))
        if quoted:
            pid = st.selectbox("Produto", [x.id for x in quoted],
                               format_func=lambda i: next(x.name for x in quoted if x.id == i))
            qs = list(s.scalars(select(PriceQuote).where(PriceQuote.product_id == pid).order_by(PriceQuote.quoted_on)))
            data = []
            for q in qs:
                v = pr.view(q)
                data.append({"data": q.quoted_on, "preço": float(v.comparable), "unidade": v.comparable_label,
                             "estabelecimento": q.establishment.name if q.establishment else "—",
                             "pago": fmt_brl(q.price), "embalagem": pr.base_qty_label(q.package_qty, q.unit),
                             "obs": q.notes or "", "id": q.id})
    if not quoted:
        st.info("Sem cotações ainda.")
    else:
        hdf = pd.DataFrame(data)
        fig = go.Figure()
        for i, (est, g) in enumerate(hdf.groupby("estabelecimento")):
            fig.add_scatter(x=g["data"], y=g["preço"], name=est, mode="lines+markers",
                            line=dict(width=2, color=ui.SERIES[i % len(ui.SERIES)]), marker=dict(size=8),
                            hovertemplate="R$ %{y:.2f}<extra>" + est + "</extra>")
        fig.update_yaxes(tickprefix="R$ ")
        ui.plot(ui.date_axis(ui.fig_layout(fig, f"Preço por {hdf['unidade'].iloc[0]}")))
        st.dataframe(hdf.drop(columns=["id"]).assign(data=hdf["data"].map(ui.fmt_date),
                                                    preço=hdf["preço"].map(lambda x: fmt_brl(x))),
                     hide_index=True, width="stretch")
        with st.expander("Apagar uma cotação"):
            qlabels = {r["id"]: f"{ui.fmt_date(r['data'])} · {r['estabelecimento']} · {r['pago']}" for r in data}
            qid = st.selectbox("Cotação", list(qlabels), format_func=qlabels.get)
            if st.checkbox("Confirmo a exclusão desta cotação") and st.button("Apagar cotação"):
                with session_scope() as s:
                    s.delete(s.get(PriceQuote, qid))
                st.rerun()

# ============================================================================ LISTA
with tabs[4]:
    with session_scope() as s:
        plan = ns.active_plan(s, p.id)
        lists = list(s.scalars(select(ShoppingList).where(ShoppingList.profile_id == p.id)
                               .order_by(ShoppingList.id.desc())))
    with st.expander("Gerar lista a partir do cardápio", expanded=not lists):
        if not plan:
            st.info("Gere um cardápio em Meu plano alimentar primeiro.")
        else:
            with st.form("nova_lista"):
                c1, c2, c3 = st.columns(3)
                first = c1.number_input("Do dia", 1, plan.days, 1)
                last = c2.number_input("Até o dia", 1, plan.days, plan.days)
                budget = c3.number_input("Quanto tenho para esta compra (R$, opcional)", 0.0, 100000.0, None, 10.0,
                                         format="%.2f")
                use_stock = st.checkbox("Descontar o que já tenho na despensa", True)
                ok = st.form_submit_button("Gerar lista consolidada", type="primary")
            if ok:
                with session_scope() as s:
                    pl = ns.load_plan(s, plan.id)
                    sl = sh.create_list(s, p.id, pl, f"{plan.name} · dias {first}–{last}",
                                        day_indexes=set(range(int(first) - 1, int(last))),
                                        budget=Decimal(str(round(budget, 2))) if budget else None, use_stock=use_stock)
                st.session_state["lista_sel"] = sl.id
                st.rerun()
            ui.note("Ingredientes repetidos viram uma linha só. Quantidades já convertidas para o peso comprado "
                    "(cru, com perdas de casca/aparas) e multiplicadas pelo número de pessoas do cardápio.")
    with st.expander("Começar compra avulsa (sem cardápio)"):
        with st.form("compra_avulsa"):
            c1, c2 = st.columns([2, 1])
            qname = c1.text_input("Nome", f"Compra de {date.today():%d/%m}")
            qbudget = c2.number_input("Quanto tenho (R$, opcional)", 0.0, 100000.0, None, 10.0, format="%.2f")
            qok = st.form_submit_button("Começar compra", type="primary")
        ui.note("Os itens entram pela aba Escanear produto, já como comprados, e o saldo é atualizado a cada um.")
        if qok:
            with session_scope() as s:
                sl = sh.create_quick_list(s, p.id, qname.strip(), money(qbudget) if qbudget else None)
            st.session_state["lista_sel"] = st.session_state["scan_lista"] = sl.id
            st.rerun()
    if lists:
        lmap = {x.id: f"{x.name} · {x.created_at:%d/%m} · {x.status}" for x in lists}
        sel = st.session_state.get("lista_sel")
        lid = st.selectbox("Lista", list(lmap), index=list(lmap).index(sel) if sel in lmap else 0, format_func=lmap.get)
        st.session_state["lista_sel"] = lid
        with session_scope() as s:
            sl = sh.load_list(s, lid)
            t = sh.totals(sl)
            ests = [e.name for e in s.scalars(select(Establishment).order_by(Establishment.name))]
            est_names = {e.id: e.name for e in s.scalars(select(Establishment))}
            cuts = sh.over_budget_cuts(sl, -t.vs_budget) if t.vs_budget is not None and t.vs_budget < 0 else []
        cur_budget = float(sl.budget) if sl.budget is not None else None
        new_budget = st.number_input("Quanto tenho para esta compra (R$)", 0.0, 100000.0, cur_budget, 10.0,
                                     format="%.2f", key=f"orc_lista{lid}",
                                     help="Pode mudar a qualquer momento, inclusive no mercado. Vazio = sem limite.")
        if (money(new_budget) if new_budget else None) != sl.budget:
            with session_scope() as s:
                s.get(ShoppingList, lid).budget = money(new_budget) if new_budget else None
            st.rerun()
        ui.tiles([
            {"label": "Previsto (embalagens inteiras)", "value": fmt_brl(t.estimated), "accent": t.budget is None},
            {"label": "Já pago", "value": fmt_brl(t.paid),
             "detail": f"previsto destes itens: {fmt_brl(t.estimated_of_purchased)}"},
            {"label": "Diferença vs previsto", "value": fmt_brl(t.vs_estimate),
             "detail": "positivo = economizou"},
            {"label": "Projeção final", "value": fmt_brl(t.projected),
             "detail": (f"valor da compra {fmt_brl(t.budget)} · sobra {fmt_brl(t.vs_budget)}" if t.budget is not None
                        else "sem valor definido")},
            *([{"label": "Ainda posso gastar", "value": fmt_brl(t.budget - t.paid), "accent": True,
                "detail": f"de {fmt_brl(t.budget)} · pendente previsto {fmt_brl(t.pending_estimated)}"}]
              if t.budget is not None else []),
        ])
        if t.budget is not None and t.paid > t.budget:
            st.error(f"O que já foi pago passou {fmt_brl(t.paid - t.budget)} do valor desta compra.")
        elif cuts:
            st.warning(f"A projeção passa {fmt_brl(-t.vs_budget)} do valor desta compra. Para caber, deixe para "
                       "depois: " + ", ".join(f"{it.label} ({fmt_brl(it.estimated_cost)})" for it in cuts) + ".")
        items = sorted(sl.items, key=lambda it: (it.purchased, it.label))
        df = pd.DataFrame([{
            "id": it.id, "comprado": it.purchased, "item": it.label,
            "necessário": fmt_qty(it.needed_base, it.base_unit), "em estoque": fmt_qty(it.stock_base, it.base_unit),
            "comprar": fmt_qty(it.to_buy_base, it.base_unit),
            "embalagens": it.packages, "embalagem": it.package_label or "sem preço",
            "previsto": float(it.estimated_cost) if it.estimated_cost is not None else None,
            "qtd comprada": float(it.purchased_qty) if it.purchased_qty is not None else None,
            "pago (R$)": float(it.paid_price) if it.paid_price is not None else None,
            "onde": est_names.get(it.establishment_id)} for it in items])
        edited = st.data_editor(
            df, hide_index=True, width="stretch", key=f"lista{lid}",
            disabled=["id", "item", "necessário", "em estoque", "comprar", "embalagens", "embalagem", "previsto"],
            column_config={"id": None,
                           "previsto": st.column_config.NumberColumn(format="R$ %.2f"),
                           "pago (R$)": st.column_config.NumberColumn(format="R$ %.2f", min_value=0),
                           "qtd comprada": st.column_config.NumberColumn(help="embalagens", min_value=0),
                           "onde": st.column_config.SelectboxColumn(options=ests)})
        c1, c2, c3 = st.columns([2, 2, 2])
        to_stock = c1.checkbox("Ao marcar comprado, lançar na despensa", True)
        if c2.button("Salvar lista", type="primary"):
            with session_scope() as s:
                est_ids = {e.name: e.id for e in s.scalars(select(Establishment))}
                for r in edited.to_dict("records"):
                    it = s.get(ShoppingItem, int(r["id"]))
                    if r["onde"]:
                        it.establishment_id = est_ids.get(r["onde"])
                    paid = None if pd.isna(r["pago (R$)"]) else r["pago (R$)"]
                    qty = None if pd.isna(r["qtd comprada"]) else r["qtd comprada"]
                    if bool(r["comprado"]) != it.purchased:
                        sh.mark_purchased(s, it, bool(r["comprado"]), paid_price=paid, qty=qty,
                                          add_to_stock=to_stock, profile_id=p.id)
                    elif it.purchased and paid is not None and money(paid) != it.paid_price:
                        it.paid_price = money(paid)
                        from database.models import Purchase
                        for pu in s.scalars(select(Purchase).where(Purchase.shopping_item_id == it.id)):
                            pu.amount = it.paid_price
            flash("Lista atualizada.")
            st.rerun()
        if sl.status == "aberta" and c3.button("Concluir lista"):
            with session_scope() as s:
                s.get(ShoppingList, lid).status = "concluida"
            st.rerun()
        ui.note("Sem valor em “pago”, o item comprado conta pelo previsto. Itens sem preço aparecem como "
                "“sem preço” e não entram no total.")
        with st.expander("Apagar esta lista"):
            if st.checkbox("Confirmo: apagar a lista e os registros de compra ligados a ela"):
                if st.button("Apagar lista"):
                    with session_scope() as s:
                        from database.models import Purchase
                        ids = [it.id for it in sh.load_list(s, lid).items]
                        for pu in s.scalars(select(Purchase).where(Purchase.shopping_item_id.in_(ids))):
                            s.delete(pu)
                        s.delete(s.get(ShoppingList, lid))
                    st.session_state.pop("lista_sel", None)
                    st.rerun()

# ============================================================================ CUSTOS
with tabs[5]:
    with session_scope() as s:
        plan = ns.active_plan(s, p.id)
        if plan:
            prices = pr.price_per_gram_map(s)
            sm = ns.summarize(s, plan, prices)
            lines = sh.plan_lines(s, p.id, plan, use_stock=False, prices=prices)
    if not plan:
        st.info("Sem cardápio ativo.")
    else:
        daily = sm.avg_daily_cost()
        people = plan.people
        ui.tiles([
            {"label": "Por dia", "value": fmt_brl(daily), "detail": f"{people} pessoa(s)", "accent": True},
            {"label": "Por semana", "value": fmt_brl(daily * 7) if daily else "—"},
            {"label": "Por mês (30 dias)", "value": fmt_brl(daily * 30) if daily else "—"},
            {"label": "Por pessoa por mês", "value": fmt_brl(daily * 30 / people) if daily else "—"},
            {"label": f"Total do período ({plan.days} dias)", "value": fmt_brl(sm.total_cost)},
        ])
        meal_cost: dict[str, list[Decimal]] = {}
        for ms_list in sm.days.values():
            for ms in ms_list:
                if ms.cost is not None:
                    meal_cost.setdefault(ms.meal.meal_type, []).append(ms.cost)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Custo médio por refeição**")
            st.dataframe(pd.DataFrame([{"refeição": k, "custo médio": fmt_brl(sum(v) / len(v))}
                                       for k, v in meal_cost.items()]), hide_index=True, width="stretch")
        with c2:
            st.markdown("**Custo por ingrediente no período**")
            ing = [{"ingrediente": ln.food.short_name or ln.food.name, "quantidade": fmt_qty(ln.need_g, "g"),
                    "consumido": float(ln.consumed_cost) if ln.consumed_cost is not None else None,
                    "embalagens": float(ln.cost) if ln.cost is not None else None} for ln in lines]
            st.dataframe(pd.DataFrame(ing).sort_values("consumido", ascending=False, na_position="last"),
                         hide_index=True, width="stretch",
                         column_config={"consumido": st.column_config.NumberColumn(format="R$ %.2f"),
                                        "embalagens": st.column_config.NumberColumn(format="R$ %.2f")})
        if sm.unpriced:
            ui.note("Sem preço (fora do total): " + ui.esc(", ".join(sorted(sm.unpriced))))

# ============================================================================ GASTOS
with tabs[6]:
    today = date.today()
    month_opts = [bs.month_key(date(today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1, 1))
                  for k in (-1, 0, 1, 2)]
    with session_scope() as s:
        months = sh.monthly_spending(s, p.id)
        this_month = month_spending(s, p.id)
        cur_key = bs.month_key()
        budget_now = bs.budget_for(s, p)
        chart_months = sorted({m for m, _ in months} | {cur_key})
        budgets = bs.budgets_by_month(s, p, sorted(set(chart_months) | set(month_opts)))
        overrides = {m for m in budgets if bs.month_override(s, p.id, m)}
    fixed = p.monthly_food_budget
    ui.tiles([{"label": "Gasto neste mês", "value": fmt_brl(this_month), "accent": True,
               "detail": f"orçamento {fmt_brl(budget_now)}" if budget_now else ""},
              {"label": "Ainda disponível no mês", "value": fmt_brl(budget_now - this_month) if budget_now else "—",
               "detail": ("valor definido para este mês" if cur_key in overrides
                          else "orçamento fixo do perfil" if fixed else "defina um orçamento abaixo")}])

    def _month_label(m: str) -> str:
        y, mo = m.split("-")
        return f"{mo}/{y}" + (" (este mês)" if m == cur_key else "")

    with st.expander("Orçamento por mês", expanded=not budget_now):
        ui.note(f"Orçamento fixo do perfil: {fmt_brl(fixed) if fixed else 'não definido'} (em Meu perfil). Aqui você "
                "muda o valor de um mês específico sem alterar o fixo.")
        with st.form("orc_mes"):
            c1, c2 = st.columns([1, 1])
            m_sel = c1.selectbox("Mês", month_opts, index=1, format_func=_month_label)
            m_val = c2.number_input("Orçamento do mês (R$)", 0.0, 100000.0, None, 10.0, format="%.2f",
                                    placeholder="vazio = usar o fixo")
            ok = st.form_submit_button("Salvar orçamento do mês", type="primary")
        if ok:
            with session_scope() as s:
                bs.set_month_budget(s, p.id, m_sel, money(m_val) if m_val else None)
            flash(f"Orçamento de {_month_label(m_sel)}: "
                  + (fmt_brl(money(m_val)) if m_val else "volta ao fixo do perfil") + ".")
            st.rerun()
        rows = [{"mês": _month_label(m), "orçamento": fmt_brl(budgets[m]) if budgets[m] else "—",
                 "origem": "deste mês" if m in overrides else ("fixo" if budgets[m] else "—")} for m in month_opts]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    if months:
        fig = go.Figure()
        fig.add_bar(x=[m for m, _ in months], y=[float(v) for _, v in months], name="Gasto",
                    marker=dict(color=ui.SERIES[0], line=dict(width=0)), hovertemplate="R$ %{y:.2f}<extra></extra>")
        if any(budgets[m] for m in chart_months):
            fig.add_scatter(x=chart_months, y=[float(budgets[m]) if budgets[m] else None for m in chart_months],
                            name="Orçamento", mode="lines+markers", line=dict(color=ui.MUTED, width=1.5, dash="dot"),
                            marker=dict(size=6, color=ui.MUTED), hovertemplate="R$ %{y:.2f}<extra>orçamento</extra>")
        fig.update_yaxes(tickprefix="R$ ")
        fig.update_xaxes(type="category")
        ui.plot(ui.fig_layout(fig, "Compras registradas por mês", 280))
    else:
        st.info("As compras aparecem aqui quando itens da lista são marcados como comprados.")
