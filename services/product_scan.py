"""Identificação de produto pela embalagem.

Ordem: código de barras lido localmente (zxing-cpp) → produto já cadastrado com esse código →
Open Food Facts (base aberta; só o código é enviado) → leitura da etiqueta pela IA, a pedido.
Nada é salvo aqui: a página mostra o resultado para conferência antes de cadastrar.
"""
from __future__ import annotations

import difflib
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

import httpx
from PIL import Image, ImageOps
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import logger
from database.models import Food, Product
from services import gemini_service as gs
from utils.units import D, UnitError, normalize_unit

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
OFF_FIELDS = "product_name_pt,product_name,generic_name_pt,brands,quantity,categories"
USER_AGENT = "FitOS/1.0 (app pessoal de planejamento alimentar)"


@dataclass
class ScanResult:
    barcode: str | None = None
    name: str | None = None
    brand: str | None = None
    package_qty: Decimal | None = None
    unit: str | None = None
    price: Decimal | None = None
    category: str | None = None
    sources: list[str] = field(default_factory=list)

    def merge(self, other: ScanResult | None) -> ScanResult:
        """Completa os campos vazios com os de outra leitura (a atual tem prioridade)."""
        if other is None:
            return self
        for f in ("barcode", "name", "brand", "package_qty", "unit", "price", "category"):
            if getattr(self, f) in (None, "") and getattr(other, f) not in (None, ""):
                setattr(self, f, getattr(other, f))
        self.sources += [x for x in other.sources if x not in self.sources]
        return self


# --------------------------------------------------------------------------- imagem e código de barras

def load_image(data: bytes, max_side: int = 1600) -> Image.Image:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    img.thumbnail((max_side, max_side))
    return img


def jpeg_bytes(img: Image.Image, max_side: int = 1280, quality: int = 85) -> bytes:
    """Cópia menor para enviar à IA (menos tokens e menos upload pelo túnel)."""
    small = img.copy()
    small.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    small.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def valid_gtin(code: str) -> bool:
    """Dígito verificador de EAN-8, UPC-A (12), EAN-13 e GTIN-14."""
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def normalize_barcode(text: str | None) -> str | None:
    code = re.sub(r"\D", "", text or "")
    return code if valid_gtin(code) else None


def decode_barcodes(img: Image.Image) -> list[str]:
    """Códigos EAN/UPC válidos encontrados na foto (tenta também em tons de cinza ampliados)."""
    import zxingcpp

    formats = (zxingcpp.BarcodeFormat.EAN13 | zxingcpp.BarcodeFormat.EAN8 | zxingcpp.BarcodeFormat.UPCA
               | zxingcpp.BarcodeFormat.UPCE)
    out: list[str] = []
    gray = ImageOps.grayscale(img)
    for variant in (img, ImageOps.autocontrast(gray), gray.resize((gray.width * 2, gray.height * 2))):
        for r in zxingcpp.read_barcodes(variant, formats=formats):
            code = normalize_barcode(r.text)
            if code and code not in out:
                out.append(code)
        if out:
            break
    return out


def find_by_barcode(s: Session, code: str) -> Product | None:
    return s.scalar(select(Product).where(Product.barcode == code).limit(1))


# --------------------------------------------------------------------------- Open Food Facts

_QTY = re.compile(r"(?:(\d+)\s*[x×]\s*)?(\d+(?:[.,]\d+)?)\s*(kg|g|gr|grs|gramas|ml|l|lt|litros?|un|unid|unidades)\b",
                  re.IGNORECASE)


def parse_quantity(text: str | None) -> tuple[Decimal, str] | None:
    """“500 g” → (500, g); “6 x 200 ml” → (1200, ml); “1,5 L” → (1.5, l)."""
    m = _QTY.search(text or "")
    if not m:
        return None
    mult, qty, unit = m.groups()
    unit = {"gr": "g", "grs": "g", "gramas": "g", "litro": "l", "litros": "l", "unidades": "un"}.get(unit.lower(),
                                                                                                     unit.lower())
    try:
        unit = normalize_unit(unit)
    except UnitError:
        return None
    value = D(qty.replace(",", ".")) * (int(mult) if mult else 1)
    return (value, unit) if value > 0 else None


_off_cache: dict[str, ScanResult | None] = {}


def lookup_open_food_facts(code: str) -> ScanResult | None:
    if code in _off_cache:
        return _off_cache[code]
    try:
        r = httpx.get(OFF_URL.format(code=code), params={"fields": OFF_FIELDS}, timeout=8,
                      headers={"User-Agent": USER_AGENT})
        data = r.json() if r.status_code in (200, 404) else None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Open Food Facts indisponível: %s", type(exc).__name__)
        return None  # falha de rede não vai para o cache: tenta de novo na próxima leitura
    prod = (data or {}).get("product") if (data or {}).get("status") == 1 else None
    if not prod:
        _off_cache[code] = None
        return None
    qty = parse_quantity(prod.get("quantity"))
    brand = (prod.get("brands") or "").split(",")[0].strip() or None
    category = re.sub(r"^[a-z]{2}:", "", (prod.get("categories") or "").split(",")[0].strip()) or None
    res = ScanResult(barcode=code, name=(prod.get("product_name_pt") or prod.get("product_name")
                                         or prod.get("generic_name_pt") or "").strip() or None,
                     brand=brand, package_qty=qty[0] if qty else None, unit=qty[1] if qty else None,
                     category=category, sources=["Open Food Facts"])
    _off_cache[code] = res
    return res


# --------------------------------------------------------------------------- etiqueta pela IA

class GLabel(BaseModel):
    legible: bool = Field(description="false se a foto não mostra um produto ou etiqueta legível")
    name: str | None = Field(default=None, description="nome genérico do produto em português, sem a marca. "
                                                        "Ex.: 'Arroz branco tipo 1', 'Peito de frango congelado'")
    brand: str | None = None
    package_qty: float | None = Field(default=None, description="conteúdo líquido da embalagem (só o número)")
    unit: Literal["kg", "g", "l", "ml", "un", "duzia"] | None = None
    price: float | None = Field(default=None, description="preço em reais na etiqueta de gôndola, se aparecer; "
                                                          "nunca estime")
    barcode: str | None = Field(default=None, description="só os dígitos do código de barras, se legíveis")
    category: str | None = Field(default=None, description="Ex.: Grãos, Carnes, Laticínios, Hortifrúti")


LABEL_PROMPT = (
    "Leia a foto de um produto de supermercado (embalagem e/ou etiqueta de preço da gôndola) e extraia os dados. "
    "Use só o que estiver escrito na imagem: campo ilegível ou ausente fica null. Preço por kg/litro da etiqueta "
    "não é o preço da embalagem; use o preço a pagar pelo item."
)


def read_label(s: Session, img: Image.Image, profile_id: int | None) -> ScanResult:
    """Lê nome, marca, conteúdo, preço e código da foto com o Gemini (uma chamada, a pedido)."""
    obj = gs.generate_structured_from_image(s, jpeg_bytes(img), "image/jpeg", LABEL_PROMPT, GLabel,
                                            purpose="leitura_etiqueta", profile_id=profile_id)
    if not obj.legible:
        raise gs.GeminiInvalidOutput("A IA não encontrou um produto legível na foto.", [])
    price = D(obj.price).quantize(Decimal("0.01")) if obj.price and 0 < obj.price < 100000 else None
    qty = D(obj.package_qty) if obj.package_qty and obj.package_qty > 0 else None
    return ScanResult(barcode=normalize_barcode(obj.barcode), name=(obj.name or "").strip() or None,
                      brand=(obj.brand or "").strip() or None, package_qty=qty, unit=obj.unit if qty else None,
                      price=price, category=obj.category, sources=["etiqueta (IA)"])


# --------------------------------------------------------------------------- correspondência local

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def match_product(s: Session, res: ScanResult) -> Product | None:
    """Produto já cadastrado: pelo código de barras ou, sem ele, pelo nome + marca."""
    if res.barcode:
        hit = find_by_barcode(s, res.barcode)
        if hit:
            return hit
    if not res.name:
        return None
    key = _norm(res.name)
    prods = [p for p in s.scalars(select(Product)) if not res.barcode or not p.barcode]
    exact = [p for p in prods if _norm(p.name) == key]
    if res.brand:
        exact = [p for p in exact if not p.brand or _norm(p.brand) == _norm(res.brand)] or exact
    return exact[0] if len(exact) == 1 else None


def suggest_food(s: Session, name: str | None) -> Food | None:
    """Alimento provável para ligar o produto novo (só sugestão; a pessoa confirma na tela)."""
    if not name:
        return None
    key = _norm(name)
    options: dict[str, int] = {}
    for p in s.scalars(select(Product).where(Product.food_id.is_not(None))):
        options.setdefault(_norm(p.name), p.food_id)
    for f in s.scalars(select(Food).where(Food.is_core.is_(True))):
        options.setdefault(_norm(f.short_name or f.name), f.id)
    contains = [k for k in options if k in key or key in k]
    hit = max(contains, key=len) if contains else None
    if hit is None:
        m = difflib.get_close_matches(key, list(options), n=1, cutoff=0.6)
        hit = m[0] if m else None
    return s.get(Food, options[hit]) if hit else None
