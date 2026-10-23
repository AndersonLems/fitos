"""Conversão de unidades e aritmética monetária com Decimal.

Unidades-base: massa em gramas (g), volume em mililitros (ml), contagem em unidades (un).
"Pacote" não é unidade: uma cotação informa o conteúdo do pacote (ex.: 500 g, 1 l, 12 un).
"""
from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

UNITS: dict[str, tuple[str, Decimal]] = {
    "kg": ("g", Decimal(1000)),
    "g": ("g", Decimal(1)),
    "l": ("ml", Decimal(1000)),
    "ml": ("ml", Decimal(1)),
    "un": ("un", Decimal(1)),
    "duzia": ("un", Decimal(12)),
}
UNIT_LABELS = {"kg": "kg", "g": "g", "l": "litro", "ml": "ml", "un": "unidade", "duzia": "dúzia"}
# rótulo do preço normalizado por unidade-base de comparação
COMPARE_LABEL = {"g": "kg", "ml": "litro", "un": "unidade"}
COMPARE_FACTOR = {"g": Decimal(1000), "ml": Decimal(1000), "un": Decimal(1)}

CENT = Decimal("0.01")


class UnitError(ValueError):
    pass


def D(value) -> Decimal:  # noqa: N802
    """Converte para Decimal sem herdar imprecisão de float."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        raise UnitError("valor ausente")
    try:
        if isinstance(value, str):
            value = value.strip().replace("R$", "").replace(" ", "")
            if "," in value:
                value = value.replace(".", "").replace(",", ".")
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise UnitError(f"valor numérico inválido: {value!r}") from exc


def money(value) -> Decimal:
    return D(value).quantize(CENT, rounding=ROUND_HALF_UP)


def normalize_unit(unit: str) -> str:
    u = (unit or "").strip().lower().replace("ú", "u").replace(".", "")
    aliases = {"quilo": "kg", "kilo": "kg", "litro": "l", "litros": "l", "lt": "l", "unidade": "un",
               "unid": "un", "und": "un", "gramas": "g", "grama": "g", "dz": "duzia", "dúzia": "duzia"}
    u = aliases.get(u, u)
    if u not in UNITS:
        raise UnitError(f"unidade desconhecida: {unit!r}")
    return u


def to_base(qty, unit: str) -> tuple[Decimal, str]:
    """Converte uma quantidade para a unidade-base. Ex.: (1.5, 'kg') -> (1500, 'g')."""
    base, factor = UNITS[normalize_unit(unit)]
    q = D(qty)
    if q < 0:
        raise UnitError("quantidade negativa")
    return q * factor, base


def from_base(qty_base, base_unit: str) -> tuple[Decimal, str]:
    """Escolhe uma unidade legível para exibir uma quantidade-base."""
    q = D(qty_base)
    if base_unit == "g" and q >= 1000:
        return q / 1000, "kg"
    if base_unit == "ml" and q >= 1000:
        return q / 1000, "l"
    return q, base_unit


def fmt_qty(qty_base, base_unit: str) -> str:
    q, u = from_base(qty_base, base_unit)
    digits = 0 if u in ("g", "ml", "un") else 2
    s = f"{q:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if digits and "," in s:
        s = s.rstrip("0").rstrip(",")
    return f"{s} {u}"


def fmt_brl(value) -> str:
    if value is None:
        return "—"
    v = money(value)
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}R$ {s}"


def convert_between(qty_base, from_base_unit: str, to_base_unit: str, *,
                    grams_per_unit: float | None = None, density_g_ml: float | None = None) -> Decimal:
    """Converte quantidades-base entre g, ml e un usando peso por unidade ou densidade."""
    q = D(qty_base)
    if from_base_unit == to_base_unit:
        return q
    pair = (from_base_unit, to_base_unit)
    if pair == ("g", "un") and grams_per_unit:
        return q / D(grams_per_unit)
    if pair == ("un", "g") and grams_per_unit:
        return q * D(grams_per_unit)
    if pair == ("g", "ml") and density_g_ml:
        return q / D(density_g_ml)
    if pair == ("ml", "g") and density_g_ml:
        return q * D(density_g_ml)
    raise UnitError(f"não é possível converter {from_base_unit} em {to_base_unit} sem peso por unidade ou densidade")


def price_per_base(price, package_qty, unit: str) -> tuple[Decimal, str]:
    """Preço por unidade-base (R$/g, R$/ml ou R$/un), sem arredondar."""
    qty_base, base = to_base(package_qty, unit)
    if qty_base <= 0:
        raise UnitError("quantidade da embalagem deve ser positiva")
    return D(price) / qty_base, base


def comparable_price(price, package_qty, unit: str) -> tuple[Decimal, str]:
    """Preço normalizado para comparação: R$/kg, R$/litro ou R$/unidade."""
    ppb, base = price_per_base(price, package_qty, unit)
    return money(ppb * COMPARE_FACTOR[base]), COMPARE_LABEL[base]


def packages_needed(need_base, package_base) -> int:
    """Número inteiro de embalagens para cobrir a necessidade (sempre arredonda para cima)."""
    need, pkg = D(need_base), D(package_base)
    if need <= 0:
        return 0
    if pkg <= 0:
        raise UnitError("embalagem inválida")
    return int((need / pkg).to_integral_value(rounding=ROUND_CEILING))
