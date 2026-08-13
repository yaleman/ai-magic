#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, sys
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

TWOPLACES = Decimal("0.01")

def money(v: Decimal) -> str:
    return f"${v.quantize(TWOPLACES, rounding=ROUND_HALF_UP):,.2f}"

def dec(obj: dict[str, Any], name: str, required=False) -> Decimal | None:
    value = obj.get(name)
    if value is None:
        if required:
            raise ValueError(f"missing required field {name!r}")
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name!r} must be numeric, got {value!r}") from exc
    if not out.is_finite():
        raise ValueError(f"{name!r} must be finite")
    return out

def integer(obj: dict[str, Any], name: str, default=None) -> int:
    value = obj.get(name, default)
    if value is None or isinstance(value, bool):
        raise ValueError(f"missing/invalid field {name!r}")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name!r} must be an integer") from exc
    if Decimal(str(value)) != Decimal(out):
        raise ValueError(f"{name!r} must be an integer")
    return out

def reqstr(obj: dict[str, Any], name: str) -> str:
    value = obj.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing/invalid required field {name!r}")
    return value.strip()

def size_text(size_ml: int, qty: int) -> str:
    if size_ml >= 1000:
        unit = f"{(Decimal(size_ml) / Decimal(1000)).normalize()}L"
    else:
        unit = f"{size_ml}mL"
    return unit if qty == 1 else f"{qty} × {unit}"

def esc(s: str) -> str:
    return s.replace("|", r"\|").replace("\n", " ")

@dataclass
class Row:
    retailer: str
    product: str
    size_ml: int
    pack_quantity: int
    price_aud: Decimal
    offer_type: str
    offer_label: str | None
    availability: str
    delivery_aud: Decimal | None
    source_url: str
    observed_at: str | None
    total_ml: int
    merchandise_per_litre: Decimal
    effective_price_aud: Decimal
    effective_per_litre: Decimal

def parse_row(obj: dict[str, Any], include_delivery: bool) -> Row:
    retailer, product, url = reqstr(obj, "retailer"), reqstr(obj, "product"), reqstr(obj, "source_url")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("source_url must be an http(s) URL")
    size_ml = integer(obj, "size_ml")
    qty = integer(obj, "pack_quantity", 1)
    if size_ml <= 0 or qty <= 0:
        raise ValueError("size_ml and pack_quantity must be > 0")
    price = dec(obj, "price_aud", True)
    assert price is not None
    delivery = dec(obj, "delivery_aud")
    if price < 0 or (delivery is not None and delivery < 0):
        raise ValueError("price/delivery must be >= 0")
    total_ml = size_ml * qty
    litres = Decimal(total_ml) / Decimal(1000)
    merch_pl = price / litres
    effective = price + (delivery or Decimal("0")) if include_delivery else price
    offer_label = obj.get("offer_label")
    return Row(
        retailer, product, size_ml, qty, price,
        str(obj.get("offer_type") or "public").strip(),
        str(offer_label).strip() if offer_label else None,
        str(obj.get("availability") or "unknown").strip(),
        delivery, url,
        str(obj.get("observed_at")).strip() if obj.get("observed_at") else None,
        total_ml, merch_pl, effective, effective / litres
    )

def offer(row: Row) -> str:
    bits = []
    if row.offer_type != "public":
        bits.append(row.offer_type)
    if row.offer_label:
        bits.append(row.offer_label)
    return ": ".join(bits) if bits else "—"

def render(rows: list[Row], include_delivery: bool) -> str:
    if include_delivery:
        lines = [
            "| Rank | Retailer | Product | Size | Listed price | Delivery | Effective price | Effective $/L | Offer | Availability |",
            "|---:|---|---|---:|---:|---:|---:|---:|---|---|"
        ]
    else:
        lines = [
            "| Rank | Retailer | Product | Size | Price | $/L | Offer | Availability |",
            "|---:|---|---|---:|---:|---:|---|---|"
        ]
    for i, row in enumerate(rows, 1):
        retailer = f"[{esc(row.retailer)}]({row.source_url})"
        if include_delivery:
            delivery = "unknown" if row.delivery_aud is None else money(row.delivery_aud)
            lines.append(
                f"| {i} | {retailer} | {esc(row.product)} | {size_text(row.size_ml, row.pack_quantity)} | "
                f"{money(row.price_aud)} | {delivery} | {money(row.effective_price_aud)} | "
                f"{money(row.effective_per_litre)}/L | {esc(offer(row))} | {esc(row.availability)} |"
            )
        else:
            lines.append(
                f"| {i} | {retailer} | {esc(row.product)} | {size_text(row.size_ml, row.pack_quantity)} | "
                f"{money(row.price_aud)} | {money(row.merchandise_per_litre)}/L | "
                f"{esc(offer(row))} | {esc(row.availability)} |"
            )
    return "\n".join(lines)

def jsonable(row: Row) -> dict[str, Any]:
    out = asdict(row)
    for k, v in list(out.items()):
        if isinstance(v, Decimal):
            out[k] = float(v)
    out["display_size"] = size_text(row.size_ml, row.pack_quantity)
    return out

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("--include-delivery", action="store_true")
    ap.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = ap.parse_args()
    try:
        raw = json.loads(args.input.read_text())
    except Exception as exc:
        print(f"error reading input: {exc}", file=sys.stderr)
        return 2
    if not isinstance(raw, list):
        print("error: input must be a JSON array", file=sys.stderr)
        return 2
    rows, errors = [], []
    for i, obj in enumerate(raw):
        if not isinstance(obj, dict):
            errors.append(f"row {i}: expected object")
            continue
        try:
            rows.append(parse_row(obj, args.include_delivery))
        except ValueError as exc:
            errors.append(f"row {i}: {exc}")
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 2
    rows.sort(key=lambda r: (r.effective_per_litre, r.effective_price_aud, r.retailer.casefold(), r.product.casefold()))
    if args.format == "json":
        print(json.dumps([jsonable(r) for r in rows], indent=2))
    else:
        print(render(rows, args.include_delivery))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
