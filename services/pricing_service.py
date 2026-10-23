"""Preços locais: cadastro, normalização, histórico e comparação entre estabelecimentos."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from database.models import Establishment, Food, PriceQuote, Product
from utils.units import (
    D, UnitError, comparable_price, convert_between, money, normalize_unit, price_per_base, to_base,
)


@dataclass
class QuoteView:
    quote: PriceQuote
    product: Product
    per_base: Decimal  # R$ por g/ml/un da embalagem
    base_unit: str
    comparable: Decimal  # R$/kg, R$/litro ou R$/unidade
    comparable_label: str
    per_gram: Decimal | None  # R$ por grama do alimento (None se não conversível)


def get_or_create_establishment(s: Session, name: str | None) -> Establishment | None:
    name = (name or "").strip()
    if not name:
        return None
    est = s.scalar(select(Establishment).where(Establishment.name == name))
    if not est:
        est = Establishment(name=name[:120])
        s.add(est)
        s.flush()
    return est


def add_quote(s: Session, product_id: int, price, package_qty, unit: str, *, establishment: str | None = None,
              quoted_on: date | None = None, notes: str | None = None) -> PriceQuote:
    p = money(price)
    if p <= 0:
        raise UnitError("O preço deve ser maior que zero.")
    if p > Decimal("100000"):
        raise UnitError("Preço fora da faixa esperada.")
    u = normalize_unit(unit)
    qty = D(package_qty)
    if qty <= 0:
        raise UnitError("A quantidade da embalagem deve ser maior que zero.")
    if not s.get(Product, product_id):
        raise UnitError("Produto inexistente.")
    est = get_or_create_establishment(s, establishment)
    q = PriceQuote(product_id=product_id, establishment_id=est.id if est else None, price=p, package_qty=qty,
                   unit=u, quoted_on=quoted_on or date.today(), notes=notes)
    s.add(q)
    s.flush()
    return q


def grams_per_base(product: Product, base_unit: str) -> Decimal | None:
    """Quantos gramas do alimento há em 1 unidade-base da embalagem."""
    try:
        return convert_between(1, base_unit, "g", grams_per_unit=product.grams_per_unit,
                               density_g_ml=product.density_g_ml)
    except UnitError:
        return None


def view(q: PriceQuote) -> QuoteView:
    per_base, base = price_per_base(q.price, q.package_qty, q.unit)
    comp, label = comparable_price(q.price, q.package_qty, q.unit)
    gpb = grams_per_base(q.product, base)
    per_gram = per_base / gpb if gpb else None
    return QuoteView(q, q.product, per_base, base, comp, label, per_gram)


def latest_quotes(s: Session, product_ids: list[int] | None = None) -> list[QuoteView]:
    """Cotação mais recente de cada (produto, estabelecimento)."""
    stmt = select(PriceQuote).options(joinedload(PriceQuote.product).joinedload(Product.food),
                                      joinedload(PriceQuote.establishment)) \
        .order_by(PriceQuote.quoted_on.desc(), PriceQuote.id.desc())
    if product_ids is not None:
        stmt = stmt.where(PriceQuote.product_id.in_(product_ids))
    seen, out = set(), []
    for q in s.scalars(stmt).unique():
        key = (q.product_id, q.establishment_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(view(q))
    return out


def best_quote_for_food(s: Session, food_id: int, cache: dict | None = None) -> QuoteView | None:
    """Menor custo por grama entre os produtos ligados ao alimento (cotações mais recentes)."""
    if cache is not None and food_id in cache:
        return cache[food_id]
    pids = list(s.scalars(select(Product.id).where(Product.food_id == food_id)))
    best = None
    if pids:
        for v in latest_quotes(s, pids):
            if v.per_gram is None:
                continue
            if best is None or v.per_gram < best.per_gram:
                best = v
    if cache is not None:
        cache[food_id] = best
    return best


def price_per_gram_map(s: Session) -> dict[int, QuoteView]:
    """food_id -> melhor cotação, para todos os alimentos com preço."""
    out: dict[int, QuoteView] = {}
    for v in latest_quotes(s):
        fid = v.product.food_id
        if fid is None or v.per_gram is None:
            continue
        if fid not in out or v.per_gram < out[fid].per_gram:
            out[fid] = v
    return out


@dataclass
class Comparison:
    product: Product
    rows: list[QuoteView]
    best: QuoteView
    worst: QuoteView

    @property
    def spread_pct(self) -> Decimal:
        if self.best.comparable == 0:
            return Decimal(0)
        return ((self.worst.comparable - self.best.comparable) / self.best.comparable * 100).quantize(Decimal("0.1"))


def compare_establishments(s: Session) -> list[Comparison]:
    by_prod: dict[int, list[QuoteView]] = {}
    for v in latest_quotes(s):
        by_prod.setdefault(v.product.id, []).append(v)
    out = []
    for rows in by_prod.values():
        rows.sort(key=lambda v: v.comparable)
        out.append(Comparison(rows[0].product, rows, rows[0], rows[-1]))
    out.sort(key=lambda c: c.product.name)
    return out


def create_product(s: Session, name: str, food_id: int | None, *, category: str | None = None,
                   brand: str | None = None, grams_per_unit: float | None = None,
                   density_g_ml: float | None = None, notes: str | None = None,
                   barcode: str | None = None) -> Product:
    name = (name or "").strip()
    if not name:
        raise UnitError("Informe o nome do produto.")
    barcode = (barcode or "").strip() or None
    if barcode and s.scalar(select(Product.id).where(Product.barcode == barcode)):
        raise UnitError(f"Já existe um produto com o código de barras {barcode}.")
    if food_id is not None and not s.get(Food, food_id):
        raise UnitError("Alimento inexistente.")
    p = Product(name=name[:160], food_id=food_id, category=category, brand=brand or None,
                grams_per_unit=grams_per_unit or None, density_g_ml=density_g_ml or None, notes=notes or None,
                barcode=barcode)
    s.add(p)
    s.flush()
    return p


def find_product(s: Session, text: str) -> Product | None:
    t = (text or "").strip().lower()
    if not t:
        return None
    prods = list(s.scalars(select(Product)))
    exact = [p for p in prods if p.name.lower() == t]
    if exact:
        return exact[0]
    partial = [p for p in prods if t in p.name.lower() or p.name.lower() in t]
    return partial[0] if len(partial) == 1 else None


def base_qty_label(qty, unit: str) -> str:
    q, base = to_base(qty, unit)
    from utils.units import fmt_qty
    return fmt_qty(q, base)
