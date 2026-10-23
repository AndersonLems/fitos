from datetime import date
from decimal import Decimal

import pytest
import zxingcpp
from PIL import Image
from sqlalchemy import select

from components import ui
from database.models import InventoryItem, Product, Purchase
from services import budget_service as bs
from services import pricing_service as pr
from services import product_scan as scan
from services import profile_service as ps
from services import shopping_service as sh
from tests.test_shopping import make_plan
from utils.units import UnitError


@pytest.fixture()
def prof(s):
    return ps.create_profile(s, "C", 30, 80, 180)


# --------------------------------------------------------------------------- orçamento

def test_month_budget_overrides_fixed(s, prof):
    prof.monthly_food_budget = Decimal("800.00")
    assert bs.budget_for(s, prof) == Decimal("800.00")
    bs.set_month_budget(s, prof.id, bs.month_key(), "650,50")
    assert bs.budget_for(s, prof) == Decimal("650.50")
    assert bs.budget_for(s, prof, "2000-01") == Decimal("800.00")  # outro mês segue o fixo
    bs.set_month_budget(s, prof.id, bs.month_key(), None)
    assert bs.budget_for(s, prof) == Decimal("800.00")
    with pytest.raises(ValueError):
        bs.set_month_budget(s, prof.id, bs.month_key(), 0)


def test_month_budget_without_fixed(s, prof):
    assert bs.budget_for(s, prof) is None
    bs.set_month_budget(s, prof.id, "2026-11", 300)
    assert bs.budgets_by_month(s, prof, ["2026-10", "2026-11"]) == {"2026-10": None, "2026-11": Decimal("300.00")}


# --------------------------------------------------------------------------- código de barras

def test_gtin_checksum():
    assert scan.valid_gtin("7891000100103")  # EAN-13
    assert scan.valid_gtin("96385074")  # EAN-8
    assert not scan.valid_gtin("7891000100104")
    assert scan.normalize_barcode(" 789 1000-100103 ") == "7891000100103"
    assert scan.normalize_barcode("123") is None


def test_decode_barcode_from_photo():
    img = Image.fromarray(zxingcpp.write_barcode(zxingcpp.BarcodeFormat.EAN13, "7891000100103", width=400,
                                                 height=160)).convert("RGB")
    canvas = Image.new("RGB", (800, 600), "white")
    canvas.paste(img, (200, 220))
    assert scan.decode_barcodes(canvas) == ["7891000100103"]
    assert scan.decode_barcodes(Image.new("RGB", (200, 200), "white")) == []


@pytest.mark.parametrize("text,expected", [
    ("500 g", (Decimal(500), "g")), ("1,5 L", (Decimal("1.5"), "l")), ("6 x 200 ml", (Decimal(1200), "ml")),
    ("Pacote 1kg", (Decimal(1), "kg")), ("sem quantidade", None), (None, None),
])
def test_parse_quantity(text, expected):
    assert scan.parse_quantity(text) == expected


def test_match_by_barcode_then_name(s):
    arroz = s.scalar(select(Product).where(Product.name == "Arroz branco tipo 1"))
    assert scan.match_product(s, scan.ScanResult(name="arroz branco tipo 1")).id == arroz.id
    arroz.barcode = "7891000100103"
    s.flush()
    assert scan.match_product(s, scan.ScanResult(barcode="7891000100103")).id == arroz.id
    # código desconhecido não casa com produto que já tem outro código
    assert scan.match_product(s, scan.ScanResult(barcode="96385074", name="Arroz branco tipo 1")) is None
    with pytest.raises(UnitError):
        pr.create_product(s, "Outro arroz", None, barcode="7891000100103")


def test_suggest_food_from_label_name(s):
    frango = s.scalar(select(Product).where(Product.name == "Peito de frango (filé)"))
    hit = scan.suggest_food(s, "Peito de frango (filé) congelado")
    assert hit is not None and hit.id == frango.food_id


# --------------------------------------------------------------------------- compra no mercado

def test_scanned_purchase_marks_pending_item(s, prof):
    plan = make_plan(s, prof.id)
    sl = sh.create_list(s, prof.id, plan, "t", budget=Decimal("50"))
    prod = s.scalar(select(Product).where(Product.name == "Peito de frango (filé)"))
    q = pr.add_quote(s, prod.id, "21,90", 1, "kg", establishment="Mercado A")
    before = len(sl.items)
    item = sh.register_scanned_purchase(s, sh.load_list(s, sl.id), q, 2, profile_id=prof.id)
    sl = sh.load_list(s, sl.id)
    assert len(sl.items) == before and item.purchased and item.paid_price == Decimal("43.80")
    assert sh.totals(sl).paid == Decimal("43.80")
    stock = s.scalar(select(InventoryItem).where(InventoryItem.profile_id == prof.id))
    assert stock.quantity == Decimal("2000.000")


def test_quick_list_adds_new_item(s, prof):
    sl = sh.create_quick_list(s, prof.id, "Compra de hoje", Decimal("100"))
    leite = s.scalar(select(Product).where(Product.name == "Leite integral"))
    q = pr.add_quote(s, leite.id, "5,50", 1, "l")
    sh.register_scanned_purchase(s, sh.load_list(s, sl.id), q, 3, profile_id=prof.id)
    sl = sh.load_list(s, sl.id)
    t = sh.totals(sl)
    assert t.paid == Decimal("16.50") and t.budget - t.paid == Decimal("83.50")
    assert s.scalar(select(Purchase).where(Purchase.profile_id == prof.id)).amount == Decimal("16.50")


def test_over_budget_cuts_most_expensive_first(s, prof):
    sl = sh.create_quick_list(s, prof.id, "x")
    for label, cost in [("a", "5"), ("b", "30"), ("c", "12")]:
        sl.items.append(sh.ShoppingItem(label=label, needed_base=1, to_buy_base=1, base_unit="g",
                                        estimated_cost=Decimal(cost)))
    s.flush()
    assert [i.label for i in sh.over_budget_cuts(sl, Decimal("35"))] == ["b", "c"]
    assert [i.label for i in sh.over_budget_cuts(sl, Decimal("1"))] == ["b"]


# --------------------------------------------------------------------------- temas

def test_themes_share_tokens():
    keys = set(ui.THEMES[ui.DEFAULT_THEME])
    for t in ui.THEMES.values():
        assert set(t) == keys and len(t["series"]) == 5
    assert len(ui.THEMES) == 3
    assert ui.SERIES == ui.THEMES[ui.DEFAULT_THEME]["series"]  # fora do Streamlit vale o padrão
    with pytest.raises(AttributeError):
        ui.NAO_EXISTE  # noqa: B018
