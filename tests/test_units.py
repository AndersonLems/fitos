from decimal import Decimal

import pytest

from utils.units import (
    D, UnitError, comparable_price, convert_between, fmt_brl, fmt_qty, money, packages_needed, price_per_base, to_base,
)


def test_decimal_parsing_brazilian_format():
    assert D("19,90") == Decimal("19.90")
    assert D("R$ 1.234,56") == Decimal("1234.56")
    assert D(0.1) + D(0.2) == Decimal("0.3")


def test_to_base():
    assert to_base("1,5", "kg") == (Decimal("1500.0"), "g")
    assert to_base(2, "litro") == (Decimal(2000), "ml")
    assert to_base(1, "dúzia") == (Decimal(12), "un")
    with pytest.raises(UnitError):
        to_base(1, "saco")
    with pytest.raises(UnitError):
        to_base(-1, "kg")


def test_comparable_price_normalizes_packages():
    assert comparable_price("27,50", 5, "kg") == (Decimal("5.50"), "kg")
    assert comparable_price("6,45", 500, "g") == (Decimal("12.90"), "kg")
    assert comparable_price("9,60", 1, "duzia") == (Decimal("0.80"), "unidade")
    assert comparable_price("4,40", 800, "ml") == (Decimal("5.50"), "litro")


def test_price_per_base_is_exact():
    ppb, base = price_per_base("10,00", 3, "kg")
    assert base == "g"
    assert money(ppb * 3000) == Decimal("10.00")


def test_conversions_need_reference():
    assert convert_between(600, "g", "un", grams_per_unit=50) == 12
    assert convert_between(1000, "ml", "g", density_g_ml=1.03) == Decimal("1030.00")
    with pytest.raises(UnitError):
        convert_between(100, "g", "un")


def test_packages_round_up():
    assert packages_needed(1001, 1000) == 2
    assert packages_needed(1000, 1000) == 1
    assert packages_needed(0, 1000) == 0


def test_formatting():
    assert fmt_brl(Decimal("1234.5")) == "R$ 1.234,50"
    assert fmt_brl(Decimal("-3")) == "-R$ 3,00"
    assert fmt_qty(1500, "g") == "1,5 kg"
    assert fmt_qty(250, "g") == "250 g"
