"""Aba “Escanear produto” do Mercado: foto ou código → produto → preço → lista da compra."""
from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

import streamlit as st
from sqlalchemy import select

from components import ui
from components.state import flash
from config.settings import gemini_api_key
from database.connection import session_scope
from database.models import Establishment, Food, Product, ShoppingList
from services import gemini_service as gs
from services import pricing_service as pr
from services import product_scan as scan
from services import shopping_service as sh
from utils.units import UNIT_LABELS, UnitError, comparable_price, fmt_brl, fmt_qty, to_base

MODES = ["Enviar foto", "Câmera", "Digitar código"]  # câmera não é o padrão: pediria permissão a cada visita


@st.cache_data(max_entries=16, show_spinner=False)
def _decode(data: bytes) -> list[str]:
    return scan.decode_barcodes(scan.load_image(data))


def _input_round() -> int:
    """Contador que troca a chave da câmera depois de salvar: a foto some e a próxima leitura começa limpa."""
    return st.session_state.setdefault("scan_n", 0)


def _next_product() -> None:
    st.session_state["scan_n"] = _input_round() + 1
    st.session_state.pop("scan_ia", None)


def _photo_and_code() -> tuple[bytes | None, str]:
    n = _input_round()
    mode = st.radio("Como identificar", MODES, horizontal=True, key="scan_modo", label_visibility="collapsed")
    if mode == "Câmera":
        shot = st.camera_input("Foto do código de barras ou da etiqueta", key=f"scan_cam{n}")
        return (shot.getvalue() if shot else None), ""
    if mode == "Enviar foto":
        up = st.file_uploader("Foto do código de barras ou da etiqueta", type=["jpg", "jpeg", "png", "webp"],
                              key=f"scan_up{n}", help="No celular, abre a câmera traseira, que foca melhor de perto.")
        return (up.getvalue() if up else None), ""
    return None, st.text_input("Código de barras", key=f"scan_txt{n}", placeholder="7891234567895").strip()


def _summary(res: scan.ScanResult, product: Product | None) -> None:
    rows = [("Código de barras", res.barcode), ("Nome lido", res.name), ("Marca", res.brand),
            ("Conteúdo", fmt_qty(*to_base(res.package_qty, res.unit)) if res.package_qty and res.unit else None),
            ("Preço na etiqueta", fmt_brl(res.price) if res.price else None), ("Categoria", res.category)]
    body = "".join(f"<li><b>{ui.esc(k)}:</b> {ui.esc(v)}</li>" for k, v in rows if v)
    title = f"Já cadastrado: {product.name}" if product else "Produto ainda não cadastrado"
    ui.card(title, f'<ul class="fx-list">{body}</ul>' if body else "<p>Nada legível além do código.</p>")


def _price_fields(prefix: str, res: scan.ScanResult, last, ests: list[str], lists: dict[int, str]):
    """Campos comuns aos dois formulários (preço, embalagem, mercado e lista da compra)."""
    c1, c2, c3, c4 = st.columns([1.3, 1.2, 1.2, 1])
    price = c1.text_input("Preço da embalagem (R$)", f"{res.price:.2f}".replace(".", ",") if res.price else "",
                          placeholder="19,90")
    qty0 = res.package_qty or (last.package_qty if last else None) or Decimal(1)
    unit0 = res.unit or (last.unit if last else "un")
    qty = c2.text_input("Quantidade da embalagem", f"{qty0.normalize():f}".replace(".", ","))
    units = list(UNIT_LABELS)
    unit = c3.selectbox("Unidade", units, index=units.index(unit0) if unit0 in units else 0,
                        format_func=UNIT_LABELS.get, key=f"{prefix}_un")
    packs = c4.number_input("Levando", 1, 99, 1, help="Quantas embalagens vão para o carrinho")
    c1, c2 = st.columns(2)
    est_default = st.session_state.get("scan_est") or (last.establishment.name if last and last.establishment
                                                       else None)
    est_opts = [*ests, "+ novo"]
    est = c1.selectbox("Estabelecimento", est_opts, placeholder="Opcional", key=f"{prefix}_est",
                       index=est_opts.index(est_default) if est_default in est_opts else None)
    new_est = c1.text_input("Novo estabelecimento", label_visibility="collapsed", key=f"{prefix}_novo",
                            placeholder="Novo estabelecimento (se escolheu “+ novo”)")
    # só pré-seleciona a lista que a pessoa escolheu para a compra em andamento (nunca uma qualquer)
    sel = st.session_state.get("scan_lista")
    keys = [None, *lists]
    lid = c2.selectbox("Lançar como comprado na lista", keys, format_func=lambda k: "Não lançar" if k is None
                       else lists[k], index=keys.index(sel) if sel in keys else 0, key=f"{prefix}_lista")
    return price, qty, unit, int(packs), (new_est.strip() if est == "+ novo" else est), lid


def _save(s, p, product_id: int, fields, barcode: str | None) -> str:
    price, qty, unit, packs, est, lid = fields
    if not price.strip():
        raise UnitError("Informe o preço da embalagem.")
    q = pr.add_quote(s, product_id, price, qty.replace(",", "."), unit, establishment=est, quoted_on=date.today(),
                     notes="lido no mercado")
    prod = s.get(Product, product_id)
    if barcode and not prod.barcode:
        prod.barcode = barcode
    comp, label = comparable_price(q.price, q.package_qty, q.unit)
    msg = f"{prod.name}: {fmt_brl(q.price)} ({fmt_brl(comp)}/{label})."
    if est:
        st.session_state["scan_est"] = est
    if lid:
        sl = sh.load_list(s, lid)
        sh.register_scanned_purchase(s, sl, q, packs, add_to_stock=True, profile_id=p.id)
        st.session_state["lista_sel"] = st.session_state["scan_lista"] = lid
        t = sh.totals(sh.load_list(s, lid))
        msg += f" Lançado em “{sl.name}”: pago {fmt_brl(t.paid)}"
        msg += f", ainda pode gastar {fmt_brl(t.budget - t.paid)}." if t.budget is not None else "."
    return msg


def render(p) -> None:
    ui.note("Fotografe o código de barras para achar o produto (no cadastro ou na base aberta Open Food Facts) "
            "ou a etiqueta, para a IA ler nome, conteúdo e preço. Confira os dados antes de salvar.")
    data, typed = _photo_and_code()
    digest = hashlib.sha1(data).hexdigest() if data else None
    codes: list[str] = []
    if data:
        try:
            codes = _decode(data)
        except Exception:  # noqa: BLE001 — arquivo que não é imagem
            st.error("Não consegui abrir essa imagem.")
            return
    code = scan.normalize_barcode(typed) if typed else (codes[0] if codes else None)
    if typed and not code:
        st.error("Código de barras inválido: confira os dígitos (EAN-8, EAN-13 ou UPC).")
        return
    if len(codes) > 1:
        code = st.selectbox("Mais de um código na foto", codes)
    ai = (st.session_state.get("scan_ia") or {}).get(digest) if digest else None

    if data:
        if not codes:
            st.info("Nenhum código de barras na foto. Aproxime e enquadre só as barras, ou leia a etiqueta com IA.")
        if gemini_api_key():
            if st.button("Ler etiqueta com IA", icon=":material/auto_awesome:", disabled=ai is not None,
                         help="Uma chamada ao Gemini: lê nome, marca, conteúdo e preço que aparecem na foto."):
                res = None
                with ui.loading("Lendo a etiqueta…"), session_scope() as s:
                    try:
                        res = scan.read_label(s, scan.load_image(data), p.id)
                    except (gs.GeminiUnavailable, gs.GeminiInvalidOutput) as exc:
                        st.error(str(exc))
                if res:
                    st.session_state["scan_ia"] = {digest: res}
                    st.rerun()
        else:
            ui.note("A leitura da etiqueta usa o Gemini: configure GEMINI_API_KEY no .env.")
    if not code and ai is None:
        return

    res = scan.ScanResult(barcode=code, sources=["código de barras"] if code else []).merge(ai)
    with session_scope() as s:
        product = scan.match_product(s, res)
        if product is None and res.barcode:
            with st.spinner("Procurando o código no Open Food Facts…"):
                res.merge(scan.lookup_open_food_facts(res.barcode))
            product = scan.match_product(s, res)
        quotes = pr.latest_quotes(s, [product.id]) if product else []
        last = max((v.quote for v in quotes), key=lambda q: (q.quoted_on, q.id), default=None)
        if last is not None:
            _ = last.establishment  # carrega antes de fechar a sessão
        ests = [e.name for e in s.scalars(select(Establishment).order_by(Establishment.name))]
        lists = {x.id: x.name for x in s.scalars(select(ShoppingList).where(
            ShoppingList.profile_id == p.id, ShoppingList.status == "aberta").order_by(ShoppingList.id.desc()))}
        products = {x.id: x.name + (f" ({x.brand})" if x.brand else "")
                    for x in s.scalars(select(Product).order_by(Product.name))}
        suggested = scan.suggest_food(s, res.name) if product is None else None
        foods = {f.id: (f.short_name or f.name) for f in
                 s.scalars(select(Food).order_by(Food.is_core.desc(), Food.short_name, Food.name))}

    _summary(res, product)
    if res.sources:
        ui.note("Fonte: " + ui.esc(", ".join(res.sources)))
    if quotes:
        ui.note("Últimos preços: " + ui.esc(" · ".join(
            f"{v.quote.establishment.name if v.quote.establishment else 'sem local'} {fmt_brl(v.comparable)}/"
            f"{v.comparable_label} ({ui.fmt_date(v.quote.quoted_on)})" for v in sorted(quotes, key=lambda v: v.comparable))))

    if product:
        with st.form(f"scan_preco{_input_round()}"):
            st.markdown(f"**Registrar preço de {ui.esc(product.name)}**")
            fields = _price_fields("sp", res, last, ests, lists)
            ok = st.form_submit_button("Salvar preço", type="primary")
        if ok:
            try:
                with session_scope() as s:
                    msg = _save(s, p, product.id, fields, res.barcode)
                flash(msg)
                _next_product()
                st.rerun()
            except UnitError as exc:
                st.error(str(exc))
        return

    with st.form(f"scan_novo{_input_round()}"):
        st.markdown("**Cadastrar produto e preço**")
        existing = st.selectbox("É um produto que já cadastrei (sem código)?", [None, *products],
                                format_func=lambda k: "Não, é novo" if k is None else products[k],
                                help="Escolhendo um, o código de barras passa a apontar para ele.")
        c1, c2, c3 = st.columns([3, 2, 2])
        name = c1.text_input("Nome", res.name or "")
        brand = c2.text_input("Marca", res.brand or "")
        cat = c3.text_input("Categoria", res.category or "", placeholder="Grãos, Carnes…")
        fkeys = [None, *foods]
        food_id = st.selectbox("Alimento que este produto fornece (custo e nutrição)", fkeys,
                               index=fkeys.index(suggested.id) if suggested else 0,
                               format_func=lambda i: "— sem vínculo —" if i is None else foods[i],
                               help="Sugestão automática pelo nome; confira.")
        c1, c2 = st.columns(2)
        gpu = c1.number_input("Peso médio por unidade (g) — se vendido por unidade", 0.0, 5000.0, None, 1.0)
        dens = c2.number_input("Densidade (g/ml) — líquidos", 0.3, 2.0, None, 0.01)
        fields = _price_fields("sn", res, None, ests, lists)
        ok = st.form_submit_button("Cadastrar e salvar preço", type="primary")
    if ok:
        try:
            with session_scope() as s:
                if existing:
                    pid = existing
                else:
                    pid = pr.create_product(s, name, food_id, category=cat.strip() or None, brand=brand.strip(),
                                            grams_per_unit=gpu, density_g_ml=dens, barcode=res.barcode).id
                msg = _save(s, p, pid, fields, res.barcode)
            flash(msg)
            _next_product()
            st.rerun()
        except UnitError as exc:
            st.error(str(exc))
