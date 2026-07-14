"""
FreightFlow / Kargo AI Engine

One shared logistics-intelligence layer powers both:
1) quote ranking (marketplace matching), and
2) the FreightFlow AI / Kargo assistant.

The engine is intentionally provider-agnostic: no Anthropic/OpenAI key is required
for the demo. If an LLM is added later, it should call this engine for grounded
facts and explanations rather than replacing the logistics logic.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from app.models import Quote, SupplierProfile, Booking, AISettings


# South African city coordinates used when Google Places lat/lng is not stored.
# This keeps demo ranking realistic without needing an external API call.
SA_CITY_COORDS: Dict[str, tuple[float, float]] = {
    "Durban": (-29.8587, 31.0218), "Johannesburg": (-26.2041, 28.0473),
    "Cape Town": (-33.9249, 18.4241), "Pretoria": (-25.7479, 28.2293),
    "Gqeberha": (-33.9608, 25.6022), "Bloemfontein": (-29.0852, 26.1596),
    "Polokwane": (-23.9045, 29.4689), "Mbombela": (-25.4753, 30.9694),
    "Nelspruit": (-25.4753, 30.9694), "Kimberley": (-28.7282, 24.7499),
    "East London": (-33.0292, 27.8546), "Pietermaritzburg": (-29.6006, 30.3794),
    "Richards Bay": (-28.7807, 32.0383), "Rustenburg": (-25.6676, 27.2421),
    "Soweto": (-26.2485, 27.8540), "Midrand": (-25.9992, 28.1263),
    "Krugersdorp": (-26.0963, 27.8076), "Randburg": (-26.0936, 28.0060),
    "Centurion": (-25.8601, 28.1894), "Benoni": (-26.1885, 28.3208),
    "Boksburg": (-26.2126, 28.2625), "Germiston": (-26.2309, 28.1670),
    "Kempton Park": (-26.0963, 28.2336), "Alberton": (-26.2679, 28.1222),
    "Springs": (-26.2547, 28.4428), "Brakpan": (-26.2366, 28.3694),
    "Vereeniging": (-26.6731, 27.9261), "Vanderbijlpark": (-26.7034, 27.8077),
    "Potchefstroom": (-26.7145, 27.0970), "Klerksdorp": (-26.8521, 26.6667),
    "Welkom": (-27.9762, 26.7351), "Bethlehem": (-28.2308, 28.3071),
    "Harrismith": (-28.2728, 29.1295), "Ladysmith": (-28.5539, 29.7827),
    "Newcastle": (-27.7576, 29.9318), "Vryheid": (-27.7695, 30.7917),
    "Pinetown": (-29.8170, 30.8570), "Umhlanga": (-29.7250, 31.0850),
    "Amanzimtoti": (-30.0522, 30.8847), "Ballito": (-29.5389, 31.2144),
    "KwaDukuza": (-29.3375, 31.2900), "Empangeni": (-28.7617, 31.8933),
    "Port Shepstone": (-30.7414, 30.4548), "Margate": (-30.8636, 30.3705),
    "George": (-33.9881, 22.4530), "Knysna": (-34.0351, 23.0465),
    "Paarl": (-33.7342, 18.9621), "Stellenbosch": (-33.9321, 18.8602),
    "Worcester": (-33.6465, 19.4485), "Somerset West": (-34.0757, 18.8433),
    "Mthatha": (-31.5889, 28.7844), "Queenstown": (-31.8976, 26.8753),
    "Makhanda": (-33.3106, 26.5256), "Grahamstown": (-33.3106, 26.5256),
    "Uitenhage": (-33.7576, 25.3971), "Middelburg": (-25.7751, 29.4648),
    "Emalahleni": (-25.8713, 29.2332), "Secunda": (-26.5150, 29.1930),
    "Sasolburg": (-26.8142, 27.8286), "Tzaneen": (-23.8332, 30.1635),
    "Phalaborwa": (-23.9430, 31.1411), "Hazyview": (-25.0430, 31.1274),
    "Komatipoort": (-25.4332, 31.9548), "Brits": (-25.6347, 27.7802),
    "Carletonville": (-26.3609, 27.3977), "Bisho": (-32.8499, 27.4422),
    "Alice": (-32.7875, 26.8344)
}


EQUIPMENT_PROFILES: Dict[str, dict] = {
    "Bakkie / LDV": {"payload_kg": 1500, "pallets": 2, "cbm": 8, "best_for": ["small loads", "SME deliveries", "local"], "cover": False},
    "Panel Van": {"payload_kg": 1400, "pallets": 2, "cbm": 10, "best_for": ["small loads", "secure cargo", "retail"], "cover": True},
    "4-Ton Rigid": {"payload_kg": 4000, "pallets": 6, "cbm": 25, "best_for": ["regional", "small pallets"], "cover": True},
    "8-Ton Rigid": {"payload_kg": 8000, "pallets": 12, "cbm": 45, "best_for": ["regional", "retail", "FMCG"], "cover": True},
    "Curtainsider": {"payload_kg": 34000, "pallets": 34, "cbm": 120, "best_for": ["pallets", "fragile", "FMCG", "retail"], "cover": True},
    "Superlink": {"payload_kg": 36000, "pallets": 36, "cbm": 125, "best_for": ["long distance", "bulk", "pallets"], "cover": True},
    "Flatbed": {"payload_kg": 34000, "pallets": 34, "cbm": 110, "best_for": ["steel", "machinery", "construction"], "cover": False},
    "Flatdeck": {"payload_kg": 34000, "pallets": 34, "cbm": 110, "best_for": ["steel", "machinery", "construction"], "cover": False},
    "Lowbed": {"payload_kg": 40000, "pallets": 0, "cbm": 100, "best_for": ["heavy machinery", "mining", "plant"], "cover": False},
    "Refrigerated": {"payload_kg": 30000, "pallets": 30, "cbm": 95, "best_for": ["cold chain", "food", "pharma"], "cover": True, "temperature": True},
    "Tanker": {"payload_kg": 32000, "pallets": 0, "cbm": 70, "best_for": ["liquids", "fuel", "chemicals"], "cover": True},
    "Skeletal Trailer": {"payload_kg": 34000, "pallets": 0, "cbm": 0, "best_for": ["containers", "ports", "20ft", "40ft"], "cover": False},
}


@dataclass
class KargoScore:
    price_score: float
    performance_score: float
    proximity_score: float
    equipment_score: float
    availability_score: float
    risk_score: float
    final_score: float
    risk_level: str
    proximity_km: Optional[float]
    equipment_label: str
    reasons: List[str]


def _safe_float(value, default=0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _city_coord(city: str | None) -> Optional[tuple[float, float]]:
    if not city:
        return None
    city_norm = str(city).strip()
    return SA_CITY_COORDS.get(city_norm) or SA_CITY_COORDS.get(city_norm.title())


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(x), math.sqrt(1 - x))


def _supplier_proximity_km(supplier: SupplierProfile, booking: Booking | None) -> Optional[float]:
    if not supplier or not booking:
        return None
    supplier_coord = _city_coord(getattr(supplier, "base_city", None))
    pickup_coord = _city_coord(getattr(booking, "collection_city", None))
    if not supplier_coord or not pickup_coord:
        return None
    return round(_haversine_km(supplier_coord, pickup_coord), 1)


def _vehicle_profile_name(vehicle_type: str | None) -> str:
    if not vehicle_type:
        return "General Freight"
    vt = str(vehicle_type).strip()
    lower = vt.lower()
    if "bakkie" in lower or "ldv" in lower:
        return "Bakkie / LDV"
    if "van" in lower:
        return "Panel Van"
    if "curtain" in lower or "taut" in lower:
        return "Curtainsider"
    if "super" in lower:
        return "Superlink"
    if "flat" in lower:
        return "Flatdeck"
    if "low" in lower:
        return "Lowbed"
    if "reefer" in lower or "refriger" in lower:
        return "Refrigerated"
    if "skeletal" in lower or "container" in lower:
        return "Skeletal Trailer"
    return vt


def equipment_fit(booking: Booking | None, vehicle_type: str | None = None) -> dict:
    """Score how well the requested cargo fits a vehicle/equipment type."""
    requested = _vehicle_profile_name(vehicle_type or getattr(booking, "vehicle_type_req", None))
    profile = EQUIPMENT_PROFILES.get(requested)
    if not profile:
        return {"score": 0.72, "label": requested, "utilisation": None,
                "reasons": ["General freight fit - details can be refined by Kargo AI."]}

    total_weight = _safe_float(getattr(booking, "total_weight_kg", 0), 0) or _safe_float(getattr(booking, "total_weight", 0), 0)
    pieces = int(_safe_float(getattr(booking, "pieces", 0), 0) or 0)
    commodity = (getattr(booking, "commodity", "") or "").lower()
    notes = (getattr(booking, "notes", "") or "").lower()
    fragile = bool(getattr(booking, "is_fragile", False))

    payload = profile.get("payload_kg") or 1
    pallet_cap = profile.get("pallets") or 0
    weight_util = total_weight / payload if payload else 0
    pallet_util = pieces / pallet_cap if pallet_cap else 0
    utilisation = max(weight_util, pallet_util)

    reasons: List[str] = []
    score = 1.0

    if utilisation <= 0.25:
        score -= 0.08
        reasons.append("Capacity is available; smaller vehicle may be cheaper if urgency allows.")
    elif utilisation <= 0.85:
        reasons.append("Cargo sits comfortably within payload/pallet capacity.")
    elif utilisation <= 1.0:
        score -= 0.12
        reasons.append("Near capacity limit; confirm dimensions before dispatch.")
    else:
        score -= 0.48
        reasons.append("Cargo may exceed this vehicle's payload or pallet capacity.")

    if fragile and not profile.get("cover"):
        score -= 0.18
        reasons.append("Fragile cargo is safer in covered/weather-protected equipment.")
    elif fragile and profile.get("cover"):
        reasons.append("Covered equipment supports fragile/weather-sensitive cargo.")

    best_for = " ".join(profile.get("best_for", [])).lower()
    if commodity and any(token in best_for for token in commodity.split()[:4]):
        score += 0.06
        reasons.append(f"Equipment is commonly used for {commodity} loads.")
    if "cold" in commodity or "frozen" in commodity or "pharma" in commodity or "temperature" in notes:
        if profile.get("temperature"):
            score += 0.12
            reasons.append("Temperature-controlled equipment matches cold-chain needs.")
        else:
            score -= 0.25
            reasons.append("Cold-chain cargo should use refrigerated equipment.")

    score = max(0.05, min(1.0, score))
    return {"score": round(score, 3), "label": requested, "utilisation": round(utilisation * 100, 1), "reasons": reasons}


def _availability_score(supplier: SupplierProfile, booking: Booking | None) -> tuple[float, List[str]]:
    reasons: List[str] = []
    try:
        vehicles = supplier.vehicles.all()
    except Exception:
        vehicles = []
    try:
        drivers = supplier.drivers.all()
    except Exception:
        drivers = []

    requested = _vehicle_profile_name(getattr(booking, "vehicle_type_req", None))
    available_vehicles = [v for v in vehicles if (getattr(v, "availability", "Available") or "Available") == "Available"]
    available_drivers = [d for d in drivers if (getattr(d, "status", "Active") or "Active") == "Active"]
    matching_vehicles = [v for v in available_vehicles if _vehicle_profile_name(getattr(v, "vehicle_type", "")) == requested]

    score = 1.0
    if not available_drivers:
        score -= 0.35
        reasons.append("No active free drivers found for immediate dispatch.")
    else:
        reasons.append(f"{len(available_drivers)} active driver(s) available.")

    if requested and requested != "General Freight" and not matching_vehicles:
        if available_vehicles:
            score -= 0.18
            reasons.append("Supplier has vehicles available, but exact equipment type is not confirmed.")
        else:
            score -= 0.35
            reasons.append("No available vehicles currently marked ready.")
    else:
        reasons.append("Requested equipment is available or suitable equivalent exists.")

    if getattr(supplier, "status", "") != "Active":
        score -= 0.5
        reasons.append("Supplier is not active and should not be selected.")

    return max(0.0, min(1.0, score)), reasons


def _risk_from_scores(perf: float, equip: float, avail: float, prox: float) -> tuple[str, float]:
    risk_raw = (1 - perf) * 0.35 + (1 - equip) * 0.30 + (1 - avail) * 0.25 + (1 - prox) * 0.10
    if risk_raw >= 0.46:
        return "High", risk_raw
    if risk_raw >= 0.25:
        return "Medium", risk_raw
    return "Low", risk_raw


def get_ai_weights() -> dict:
    """Read admin AI weights and add Kargo-specific dimensions."""
    try:
        settings = AISettings.get()
        price = max(0, _safe_float(settings.price_weight, 50))
        perf = max(0, _safe_float(settings.performance_weight, 35))
        prox = max(0, _safe_float(settings.proximity_weight, 15))
    except Exception:
        price, perf, prox = 50, 35, 15
    # Add two product dimensions without breaking older admin UI.
    equipment = 20
    availability = 10
    total = price + perf + prox + equipment + availability
    if total <= 0:
        total = 1
    return {
        "price": price / total,
        "performance": perf / total,
        "proximity": prox / total,
        "equipment": equipment / total,
        "availability": availability / total,
    }


def score_single_quote(quote: Quote, min_amt: float, max_amt: float, weights: Optional[dict] = None) -> KargoScore:
    booking = quote.booking
    supplier: SupplierProfile = quote.supplier
    weights = weights or get_ai_weights()
    amt_range = max(max_amt - min_amt, 1)

    price_score = 1 - ((_safe_float(quote.amount, min_amt) - min_amt) / amt_range)
    price_score = max(0.0, min(1.0, price_score))
    performance_score = max(0.0, min(1.0, _safe_float(getattr(supplier, "score", 4.0), 4.0) / 5.0))

    prox_km = _supplier_proximity_km(supplier, booking)
    try:
        radius = max(30, int(getattr(AISettings.get(), "proximity_radius_km", 30) or 30))
    except Exception:
        radius = 30
    if prox_km is None:
        proximity_score = 0.55
    else:
        # Do not hard-fail long-distance suppliers; taper down to 0.1.
        proximity_score = max(0.1, min(1.0, 1 - (prox_km / max(radius * 8, 1))))

    equip = equipment_fit(booking, getattr(booking, "vehicle_type_req", None))
    availability_score, avail_reasons = _availability_score(supplier, booking)
    risk_level, risk_raw = _risk_from_scores(performance_score, equip["score"], availability_score, proximity_score)

    final = (
        price_score * weights["price"] +
        performance_score * weights["performance"] +
        proximity_score * weights["proximity"] +
        equip["score"] * weights["equipment"] +
        availability_score * weights["availability"]
    )

    reasons: List[str] = []
    if price_score >= 0.85:
        reasons.append("Highly competitive price for this route.")
    elif price_score >= 0.55:
        reasons.append("Price is within the competitive range.")
    else:
        reasons.append("Higher price, but may still win on reliability or equipment fit.")

    if performance_score >= 0.9:
        reasons.append(f"Excellent supplier reliability score: {supplier.score}/5.")
    elif performance_score >= 0.75:
        reasons.append(f"Solid supplier reliability score: {supplier.score}/5.")
    else:
        reasons.append(f"Supplier reliability requires attention: {supplier.score}/5.")

    if prox_km is not None:
        reasons.append(f"Depot is approximately {prox_km} km from pickup.")
    else:
        reasons.append("Depot distance estimated from available city data.")
    reasons.extend(equip.get("reasons") or [])
    reasons.extend(avail_reasons[:2])
    reasons.append(f"Kargo risk rating: {risk_level}.")

    return KargoScore(
        price_score=round(price_score, 4),
        performance_score=round(performance_score, 4),
        proximity_score=round(proximity_score, 4),
        equipment_score=round(equip["score"], 4),
        availability_score=round(availability_score, 4),
        risk_score=round(1 - risk_raw, 4),
        final_score=round(final, 4),
        risk_level=risk_level,
        proximity_km=prox_km,
        equipment_label=equip["label"],
        reasons=reasons,
    )


def score_quotes(quotes: List[Quote], price_w=None, perf_w=None, prox_w=None) -> List[Quote]:
    """Score and rank quote objects in-place using the shared Kargo AI engine."""
    if not quotes:
        return quotes
    amounts = [_safe_float(q.amount, 0) for q in quotes]
    min_amt, max_amt = min(amounts), max(amounts)
    weights = get_ai_weights()
    if price_w is not None or perf_w is not None or prox_w is not None:
        # Backwards-compatible override if older code passes weights manually.
        p = _safe_float(price_w, weights["price"])
        pf = _safe_float(perf_w, weights["performance"])
        pr = _safe_float(prox_w, weights["proximity"])
        eq = weights["equipment"]
        av = weights["availability"]
        total = p + pf + pr + eq + av
        weights = {"price": p/total, "performance": pf/total, "proximity": pr/total, "equipment": eq/total, "availability": av/total}

    for q in quotes:
        k = score_single_quote(q, min_amt, max_amt, weights)
        q.ai_score = k.final_score
        # Store a compact explanation on the quote notes for templates/API reuse without schema migration.
        q._kargo_score = k

    sorted_quotes = sorted(quotes, key=lambda q: q.ai_score or 0, reverse=True)
    for i, q in enumerate(sorted_quotes, 1):
        q.rank = i
    return sorted_quotes


def explain_rank(quote: Quote) -> dict:
    """Human-readable Kargo explanation for quote card, assistant and audit views."""
    # Recalculate if the quote came from DB without transient _kargo_score.
    k: Optional[KargoScore] = getattr(quote, "_kargo_score", None)
    if not k:
        sibling_amounts = []
        try:
            sibling_amounts = [q.amount for q in quote.booking.quotes.all()]
        except Exception:
            sibling_amounts = [quote.amount]
        k = score_single_quote(quote, min(sibling_amounts), max(sibling_amounts))
    supplier = quote.supplier
    return {
        "rank": quote.rank,
        "ai_score": quote.ai_score or k.final_score,
        "supplier": supplier.company_name,
        "amount": quote.amount,
        "risk_level": k.risk_level,
        "proximity_km": k.proximity_km,
        "equipment": k.equipment_label,
        "score_breakdown": {
            "price": k.price_score,
            "performance": k.performance_score,
            "proximity": k.proximity_score,
            "equipment_fit": k.equipment_score,
            "availability": k.availability_score,
            "risk": k.risk_score,
        },
        "reasons": k.reasons,
    }


def recommend_equipment(booking: Booking) -> dict:
    """Return the best equipment recommendations for a booking."""
    rows = []
    for name in EQUIPMENT_PROFILES:
        fit = equipment_fit(booking, name)
        rows.append({"name": name, **fit})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return {"recommended": rows[0], "alternatives": rows[1:4], "all": rows}


def booking_intelligence(booking: Booking) -> dict:
    """Shared booking-level intelligence for dashboards and Kargo assistant."""
    quotes = booking.quotes.all() if hasattr(booking.quotes, "all") else []
    ranked = score_quotes([q for q in quotes if q.status in ("Pending", "Accepted")]) if quotes else []
    best = ranked[0] if ranked else None
    best_explain = explain_rank(best) if best else None
    equipment = recommend_equipment(booking)
    warnings = []
    if equipment["recommended"]["score"] < 0.65:
        warnings.append("The requested equipment may not fit the load perfectly.")
    if getattr(booking, "is_fragile", False) and not EQUIPMENT_PROFILES.get(equipment["recommended"]["name"], {}).get("cover"):
        warnings.append("Fragile cargo should use covered equipment where possible.")
    if getattr(booking, "distance_km", 0) and booking.distance_km > 800:
        warnings.append("Long-haul route: confirm driver rest planning and ETA buffer.")
    return {
        "booking_ref": booking.ref,
        "route": booking.route,
        "status": booking.status,
        "best_quote": best_explain,
        "equipment_recommendation": equipment,
        "warnings": warnings,
        "summary": _booking_summary_text(booking, best_explain, equipment, warnings),
    }


def _booking_summary_text(booking: Booking, best_explain: Optional[dict], equipment: dict, warnings: list[str]) -> str:
    parts = [f"{booking.ref} on {booking.route or 'the selected route'} is currently {booking.status}."]
    rec = equipment["recommended"]
    parts.append(f"Kargo recommends {rec['name']} with {round(rec['score']*100)}% equipment fit.")
    if best_explain:
        parts.append(f"Best quote: {best_explain['supplier']} at R{best_explain['amount']:,.0f}, risk {best_explain['risk_level']}.")
    if warnings:
        parts.append("Watch-outs: " + "; ".join(warnings[:2]))
    return " ".join(parts)


def assistant_answer(shipper, question: str) -> str:
    """Rule-based FreightFlow AI / Kargo assistant grounded in the same engine as quote ranking."""
    q = (question or "").lower().strip()
    bookings = shipper.bookings.order_by(Booking.created_at.desc()).all() if shipper else []
    active = [b for b in bookings if b.status not in ("Delivered", "Cancelled")]
    delivered = [b for b in bookings if b.status == "Delivered"]
    total_spend = sum(_safe_float(b.quoted_value, 0) for b in bookings)

    if not bookings:
        return "You do not have shipments yet. Start with New Shipment and Kargo will recommend equipment, rank suppliers, and explain the best quote before you book."

    latest = bookings[0]
    intel = booking_intelligence(latest)

    if any(w in q for w in ["why", "rank", "supplier", "best", "quote", "recommend"]):
        if intel["best_quote"]:
            bq = intel["best_quote"]
            reasons = " ".join(f"- {r}" for r in bq["reasons"][:4])
            return f"For {latest.ref}, Kargo's best match is {bq['supplier']} at R{bq['amount']:,.0f} with a {round((bq['ai_score'] or 0)*100)}% match score. {reasons}"
        return f"For {latest.ref}, Kargo recommends {intel['equipment_recommendation']['recommended']['name']} but there are no active quotes to rank yet."

    if any(w in q for w in ["equipment", "vehicle", "truck", "bakkie", "trailer", "fit"]):
        rec = intel["equipment_recommendation"]["recommended"]
        alts = ", ".join(a["name"] for a in intel["equipment_recommendation"]["alternatives"][:2])
        return f"Kargo recommends {rec['name']} for {latest.ref} with {round(rec['score']*100)}% fit. Reason: {' '.join(rec['reasons'][:2])} Alternatives: {alts}."

    if any(w in q for w in ["risk", "delay", "late", "problem"]):
        warnings = intel["warnings"]
        if warnings:
            return f"Kargo found {len(warnings)} watch-out(s) on {latest.ref}: " + "; ".join(warnings[:3])
        return f"No major Kargo risk warnings on {latest.ref}. Current status is {latest.status}."

    if any(w in q for w in ["status", "where", "track", "current"]):
        return f"Latest shipment {latest.ref}: {latest.status}. Route: {latest.route}. Active shipments: {len(active)}. Delivered shipments: {len(delivered)}."

    if any(w in q for w in ["spend", "cost", "money", "total"]):
        return f"Your total logistics spend is R{total_spend:,.0f} across {len(bookings)} booking(s). Kargo can also explain the price, risk and equipment fit of your latest quote."

    if any(w in q for w in ["health", "score", "performance"]):
        h = compute_health_score(shipper)
        return f"Your Logistics Health Score is {h['health_score']}/100. Cost efficiency: {h['cost_efficiency']}%, reliability: {h['reliability']}%, delivery performance: {h['performance']}%."

    return intel["summary"]


# Existing health score retained, but now considered part of the same Kargo engine.
def compute_health_score(shipper_profile) -> dict:
    bookings = shipper_profile.bookings.all()
    if not bookings:
        return {"health_score": 75, "cost_efficiency": 75, "reliability": 75,
                "performance": 75, "booking_success": 75, "total_bookings": 0,
                "delivered": 0, "avg_cost_per_km": 0, "on_time_rate": 0,
                "spend": []}

    total = len(bookings)
    delivered = sum(1 for b in bookings if b.status == "Delivered")
    confirmed = sum(1 for b in bookings if b.status not in ("Pending Quotes", "Cancelled"))
    delivery_rate = (delivered / total) * 100 if total else 100
    booking_success = (confirmed / total) * 100 if total else 100

    costs_per_km = [b.quoted_value / b.distance_km for b in bookings if b.distance_km and b.quoted_value]
    if costs_per_km:
        avg_cpk = sum(costs_per_km) / len(costs_per_km)
        cost_efficiency = min(100, max(0, 100 - ((avg_cpk - 26) / 26) * 100))
    else:
        avg_cpk = 0
        cost_efficiency = 80

    supplier_scores = [b.supplier.score for b in bookings if b.supplier and b.supplier.score]
    reliability = (sum(supplier_scores) / len(supplier_scores) / 5.0 * 100) if supplier_scores else 80
    performance = min(100, delivery_rate)
    health_score = int((cost_efficiency * 0.30) + (reliability * 0.30) + (performance * 0.25) + (booking_success * 0.15))

    from datetime import date
    month_rows = []
    today = date.today().replace(day=1)
    for i in range(5, -1, -1):
        month = today.month - i
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        label_date = date(year, month, 1)
        rows = [b for b in bookings if b.created_at and b.created_at.year == year and b.created_at.month == month]
        month_rows.append({"month": label_date.strftime("%b"), "total": round(sum(b.quoted_value or 0 for b in rows), 2)})

    return {
        "health_score": health_score,
        "cost_efficiency": round(cost_efficiency, 1),
        "reliability": round(reliability, 1),
        "performance": round(performance, 1),
        "booking_success": round(booking_success, 1),
        "total_bookings": total,
        "delivered": delivered,
        "avg_cost_per_km": round(avg_cpk, 2),
        "on_time_rate": round(delivery_rate, 1),
        "spend": month_rows,
    }
