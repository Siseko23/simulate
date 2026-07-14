"""
Shipper blueprint - all routes backed by real SQLAlchemy queries.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import login_required, current_user
from datetime import date, datetime, timedelta
from functools import wraps
import io, csv
import math
import os

from app.models import (db, Booking, Quote, Invoice, Notification,
                         ShipperProfile, SupplierProfile, AddressBook,
                         BookingStatusEvent, User, ShipperDocument,
                         GITInsurance, PODToken, PurchaseOrder)
from app.services.ai_engine import score_quotes, explain_rank, compute_health_score, assistant_answer, booking_intelligence
from app.services.notifications import push_notification
from app.services.v19_adapter import booking_to_v19, quote_to_v19
from app.services.audit import log_action
from app.services.order_workflow import ensure_shipper_order, apply_shipper_payment_terms
from app.services.lifecycle import (can_select_quote, can_pay_booking, can_reallocate, can_view_waybill, can_generate_pod_token, can_scan_pod, start_supplier_response_sla, SUPPLIER_SLA_HOURS)
from app.services.finance import log_finance_event
from app.services.google_maps import has_google_maps_key, geocode_address, route_distance_km
from app.services.capacity_planner import CITY_COORDS

shipper_bp = Blueprint("shipper", __name__)

# ── Booking flow guardrails ────────────────────────────────────────────────
# The original demo only allowed a small hard-coded set of city-to-city routes.
# With Google Places enabled, the platform should accept any South African
# address/city returned by Google and use GPS coordinates where available.
# This list now only powers the datalist hints and province/city fallbacks; it is
# not a restriction gate.
SA_CITIES = {
    "Alberton","Alice","Amanzimtoti","Ballito","Benoni","Bethlehem","Bisho",
    "Bloemfontein","Boksburg","Brakpan","Brits","Cape Town","Carletonville",
    "Centurion","Durban","East London","Emalahleni","Empangeni","George",
    "Germiston","Gqeberha","Grahamstown","Harrismith","Hazyview","Howick",
    "Johannesburg","Kempton Park","Kimberley","Klerksdorp","Knysna",
    "Komatipoort","Krugersdorp","KwaDukuza","Ladysmith","Makhanda","Margate",
    "Mbombela","Middelburg","Midrand","Mthatha","Newcastle","Nelspruit",
    "Paarl","Phalaborwa","Pietermaritzburg","Pinetown","Polokwane",
    "Port Shepstone","Potchefstroom","Pretoria","Queenstown","Randburg",
    "Richards Bay","Rustenburg","Sasolburg","Secunda","Somerset West",
    "Soweto","Springs","Stellenbosch","Tzaneen","Uitenhage","Umhlanga",
    "Vanderbijlpark","Vereeniging","Vryheid","Welkom","Worcester"
}

# Approximate city coordinates for demo fallback only. Google/Places lat/lng
# always wins. These prevent valid SA cities like Krugersdorp from being blocked
# when Google billing/API restrictions return REQUEST_DENIED.
SA_CITY_COORDS = {
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

# Legacy route table remains as a fast fallback for common demo routes.
SA_ROUTE_DISTANCES = {
    frozenset(["Durban", "Johannesburg"]): 588,
    frozenset(["Durban", "Pretoria"]): 645,
    frozenset(["Durban", "Cape Town"]): 1753,
    frozenset(["Durban", "Gqeberha"]): 750,
    frozenset(["Durban", "Bloemfontein"]): 620,
    frozenset(["Durban", "East London"]): 660,
    frozenset(["Durban", "Richards Bay"]): 180,
    frozenset(["Durban", "Pietermaritzburg"]): 80,
    frozenset(["Johannesburg", "Cape Town"]): 1404,
    frozenset(["Johannesburg", "Pretoria"]): 58,
    frozenset(["Johannesburg", "Bloemfontein"]): 397,
    frozenset(["Johannesburg", "Gqeberha"]): 1050,
    frozenset(["Johannesburg", "East London"]): 970,
    frozenset(["Johannesburg", "Polokwane"]): 295,
    frozenset(["Johannesburg", "Nelspruit"]): 360,
    frozenset(["Johannesburg", "Rustenburg"]): 120,
    frozenset(["Johannesburg", "Kimberley"]): 473,
    frozenset(["Johannesburg", "Krugersdorp"]): 36,
    frozenset(["Cape Town", "Gqeberha"]): 770,
    frozenset(["Cape Town", "Bloemfontein"]): 999,
    frozenset(["Cape Town", "East London"]): 1040,
    frozenset(["Pretoria", "Polokwane"]): 270,
    frozenset(["Pretoria", "Nelspruit"]): 330,
    frozenset(["Midrand", "Johannesburg"]): 30,
    frozenset(["Midrand", "Pretoria"]): 45,
    frozenset(["Soweto", "Johannesburg"]): 20,
}


def _clean(value):
    return (value or "").strip()


def _form_get(form, *names, default=""):
    """Read both legacy snake_case and v15/v19 camelCase form fields."""
    for name in names:
        value = form.get(name)
        if value not in (None, ""):
            return value
    return default




def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _haversine_km(lat1, lng1, lat2, lng2):
    """Approximate road distance fallback from two GPS points.

    Haversine gives straight-line distance, so we apply a road-network factor.
    Google Distance Matrix remains preferred whenever available.
    """
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    straight = 2 * r * math.asin(math.sqrt(a))
    return round(max(straight * 1.22, 5), 1)


def _coords_from_form_or_city(form, lat_name, lng_name, city):
    lat = _to_float(_form_get(form, lat_name))
    lng = _to_float(_form_get(form, lng_name))
    if lat is not None and lng is not None:
        return lat, lng
    return SA_CITY_COORDS.get(city)


def validate_shipment_request(form):
    """Demo-safe validation before a shipment can enter the quote engine."""
    errors = []
    collection_address = _clean(_form_get(form, "collection_address", "collectionAddress"))
    delivery_address = _clean(_form_get(form, "delivery_address", "deliveryAddress"))
    collection_city = _clean(_form_get(form, "collection_city", "pickupCity"))
    delivery_city = _clean(_form_get(form, "delivery_city", "dropoffCity"))

    required = {
        "collection address": collection_address,
        "delivery address": delivery_address,
        "collection city": collection_city,
        "delivery city": delivery_city,
        "commodity": _clean(_form_get(form, "commodity", "commodityType")),
        "vehicle type": _clean(_form_get(form, "vehicle_type", "vehicleType")),
        "collection contact": _clean(_form_get(form, "collection_contact", "pickupContactName")),
        "collection phone": _clean(_form_get(form, "collection_phone", "pickupContactPhone")),
        "delivery contact": _clean(_form_get(form, "delivery_contact", "dropoffContactName")),
        "delivery phone": _clean(_form_get(form, "delivery_phone", "dropoffContactPhone")),
    }
    missing = [label for label, value in required.items() if not value]
    if missing:
        errors.append("Missing required shipment information: " + ", ".join(missing) + ".")

    # Do not block cities just because they are not in the old demo list.
    # Google Places can return any valid South African locality/suburb.
    if collection_city and delivery_city and collection_city == delivery_city:
        errors.append("Collection and delivery cities cannot be the same.")

    distance = None
    google_failed_softly = False

    # Prefer Google Maps when configured so real SA addresses/routes can be validated.
    # If the API key is restricted/not enabled (REQUEST_DENIED) or the API is temporarily
    # unavailable, do not block the demo flow. Fall back to the supported SA route table.
    if has_google_maps_key() and collection_address and delivery_address:
        pickup = geocode_address(collection_address, collection_city)
        dropoff = geocode_address(delivery_address, delivery_city)
        if pickup.get("ok") and dropoff.get("ok"):
            route = route_distance_km(pickup["formatted_address"], dropoff["formatted_address"])
            if route.get("ok"):
                distance = route["distance_km"]
            else:
                google_failed_softly = True
        else:
            google_failed_softly = True

    # Fallback chain whenever Google is missing, denied, or unreachable:
    # 1) legacy route table; 2) Places lat/lng; 3) known city coordinates.
    if distance is None:
        distance = SA_ROUTE_DISTANCES.get(frozenset([collection_city, delivery_city]))

    if distance is None:
        pickup_coords = _coords_from_form_or_city(form, "pickupLat", "pickupLng", collection_city)
        dropoff_coords = _coords_from_form_or_city(form, "dropoffLat", "dropoffLng", delivery_city)
        if pickup_coords and dropoff_coords:
            distance = _haversine_km(pickup_coords[0], pickup_coords[1], dropoff_coords[0], dropoff_coords[1])

    if distance is None and collection_city and delivery_city:
        # Last-resort demo-safe estimate. This keeps the quote flow usable for
        # any South African city captured by Google Places while avoiding the old
        # "city not supported" blocker. Production should require a Google route.
        distance = 250.0

    try:
        pieces = int(_form_get(form, "pieces", "quantity", "containerQty", default=0) or 0)
    except ValueError:
        pieces = 0
    try:
        weight_per_item = float(_form_get(form, "weight_per_item", "weightPerItem", "weight", "weight_kg", default=0) or 0)
    except ValueError:
        weight_per_item = 0
    if pieces <= 0:
        errors.append("Pieces/pallets must be greater than zero.")
    unit_type = _form_get(form, "unitType", "unit_type", default="pieces")
    if weight_per_item <= 0 and unit_type != "container":
        errors.append("Weight per item must be greater than zero.")

    return errors, distance


def create_or_refresh_invoice(booking):
    """Create an unpaid invoice immediately after quote selection."""
    invoice = booking.invoice
    amount = float(booking.quoted_value or 0)
    vat = round(amount * 0.15, 2)
    total = round(amount + vat, 2)
    if not invoice:
        invoice = Invoice(booking_id=booking.id, amount=amount, vat_amount=vat,
                          total_amount=total, status="Unpaid",
                          due_date=date.today() + timedelta(days=7))
        # invoice_number is NOT NULL, so assign it before the first flush.
        invoice.invoice_number = f"INV-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{booking.id}"
        db.session.add(invoice)
    else:
        invoice.amount = amount
        invoice.vat_amount = vat
        invoice.total_amount = total
        if invoice.status != "Paid":
            invoice.status = "Unpaid"
            invoice.paid_at = None
    return invoice


def shipper_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != "shipper":
            flash("Access denied.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def get_shipper():
    return ShipperProfile.query.filter_by(user_id=current_user.id).first_or_404()


# ── Dashboard ─────────────────────────────────────────────────────────────────

@shipper_bp.route("/")
@shipper_required
def dashboard():
    shipper = get_shipper()
    bookings = shipper.bookings.order_by(Booking.created_at.desc()).limit(5).all()
    total_bookings = shipper.bookings.count()
    active = shipper.bookings.filter(
        Booking.status.in_(["Confirmed","Driver Assigned","Collected","In Transit"])).count()
    delivered = shipper.bookings.filter_by(status="Delivered").count()
    total_spend = db.session.query(db.func.sum(Booking.quoted_value))\
                    .filter_by(shipper_id=shipper.id).scalar() or 0
    notifications = current_user.notifications.filter_by(is_read=False)\
                        .order_by(Notification.created_at.desc()).limit(5).all()
    return render_template("shipper/dashboard.html",
        title="Dashboard",
        shipper=shipper,
        bookings=[booking_to_v19(b) for b in bookings],
        total_bookings=total_bookings, active=active,
        delivered=delivered, total_spend=total_spend,
        notifications=notifications)


# ── Bookings ──────────────────────────────────────────────────────────────────

@shipper_bp.route("/bookings")
@shipper_required
def bookings():
    shipper  = get_shipper()
    status   = request.args.get("status", "")
    q_search = request.args.get("q", "")
    query    = shipper.bookings.order_by(Booking.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    if q_search:
        query = query.filter(Booking.ref.ilike(f"%{q_search}%") |
                             Booking.route.ilike(f"%{q_search}%") |
                             Booking.commodity.ilike(f"%{q_search}%"))
    all_bookings = query.all()
    return render_template("shipper/bookings.html",
        title="My Bookings",
        bookings=[booking_to_v19(b) for b in all_bookings],
        shipper=shipper, status_filter=status, search=q_search)


@shipper_bp.route("/bookings/new", methods=["GET","POST"])
@shipper_required
def new_booking():
    shipper = get_shipper()
    address_book = shipper.address_book.all()
    suppliers    = SupplierProfile.query.filter_by(status="Active").all()

    if request.method == "POST":
        validation_errors, validated_distance = validate_shipment_request(request.form)
        if validation_errors:
            for err in validation_errors:
                flash(err, "error")
            return render_template("shipper/shipment.html",
                title="New Shipment", shipper=shipper, address_book=address_book, suppliers=suppliers,
                form=request.form, cities=sorted(SA_CITIES), settings={"volumetricDivisor": 4000}), 400

        b = Booking(shipper_id=shipper.id)
        b.generate_ref()
        b.collection_address = _form_get(request.form, "collection_address", "collectionAddress")
        b.collection_city    = _form_get(request.form, "collection_city", "pickupCity")
        b.delivery_address   = _form_get(request.form, "delivery_address", "deliveryAddress")
        b.delivery_city      = _form_get(request.form, "delivery_city", "dropoffCity")
        def _coord(name):
            try:
                value = request.form.get(name)
                return float(value) if value not in (None, "") else None
            except (TypeError, ValueError):
                return None
        b.collection_lat = _coord("pickupLat")
        b.collection_lng = _coord("pickupLng")
        b.delivery_lat = _coord("dropoffLat")
        b.delivery_lng = _coord("dropoffLng")
        if b.collection_lat is None or b.collection_lng is None:
            fallback = CITY_COORDS.get((b.collection_city or "").lower())
            if fallback: b.collection_lat, b.collection_lng = fallback
        if b.delivery_lat is None or b.delivery_lng is None:
            fallback = CITY_COORDS.get((b.delivery_city or "").lower())
            if fallback: b.delivery_lat, b.delivery_lng = fallback
        b.route              = f"{b.collection_city} -> {b.delivery_city}"
        b.commodity          = _form_get(request.form, "commodity", "commodityType")
        b.pieces             = int(_form_get(request.form, "pieces", "quantity", "containerQty", default=1) or 1)
        b.weight_per_item_kg = float(_form_get(request.form, "weight_per_item", "weightPerItem", "weight", "weight_kg", default=0) or 0)
        b.total_weight_kg    = b.pieces * b.weight_per_item_kg
        b.vehicle_type_req   = _form_get(request.form, "vehicle_type", "vehicleType")
        b.destination_type   = request.form.get("destination_type","Direct")
        b.collection_contact = _form_get(request.form, "collection_contact", "pickupContactName")
        b.collection_phone   = _form_get(request.form, "collection_phone", "pickupContactPhone")
        b.delivery_contact   = _form_get(request.form, "delivery_contact", "dropoffContactName")
        b.delivery_phone     = _form_get(request.form, "delivery_phone", "dropoffContactPhone")
        b.notes              = request.form.get("notes","")
        b.is_fragile         = request.form.get("is_fragile") == "1"

        col_date = _form_get(request.form, "collection_date", "collectionDate")
        if col_date:
            try:
                b.collection_date = datetime.fromisoformat(col_date).date()
            except ValueError:
                b.collection_date = date.fromisoformat(col_date[:10])

        b.status = "Pending Quotes"
        db.session.add(b)
        db.session.flush()  # get b.id before creating quotes

        # ── Auto-generate AI-ranked quotes from all active suppliers ──────────
        import random

        # Use only validated demo routes. No silent 500 km fallback.
        distance = validated_distance
        b.distance_km = distance

        # Base rate per km by vehicle type (ZAR/km)
        base_rates = {
            "4-Ton Rigid":   22,
            "8-Ton Rigid":   28,
            "Superlink":     38,
            "Flatbed":       32,
            "Refrigerated":  42,
            "Tanker":        40,
        }
        base_rate        = base_rates.get(b.vehicle_type_req, 30)
        active_suppliers = SupplierProfile.query.filter_by(status="Active").all()

        generated_quotes = []
        for sup in active_suppliers:
            # Higher-scored suppliers price slightly tighter
            score_factor = 1.0 - ((sup.score or 4.0) - 4.0) * 0.05
            variance     = random.uniform(0.90, 1.10)
            amount       = round(base_rate * distance * score_factor * variance, -2)
            amount       = max(amount, 1500)

            q = Quote(
                booking_id=b.id,
                supplier_id=sup.id,
                amount=amount,
                transit_days=max(1, round(distance / 500)),
                notes=f"Competitive rate for {b.route}. GPS tracked, full insurance.",
                status="Pending",
            )
            db.session.add(q)
            generated_quotes.append(q)

            push_notification(sup.user_id, f"New quote request: {b.ref}",
                              f"New load on {b.route} - your quote has been pre-submitted.",
                              type="info", ref_type="booking", ref_id=b.ref)

        db.session.flush()

        # Run AI scoring - ranks all quotes, best = rank 1
        if generated_quotes:
            from app.services.ai_engine import score_quotes as _score
            _score(generated_quotes)
            b.status = "Quotes Received"

        db.session.commit()
        log_action(current_user.id, "CREATE_BOOKING", "Booking", b.ref)
        n_quotes = len(generated_quotes)
        flash(f"Booking {b.ref} created - {n_quotes} AI-ranked supplier quote{'s' if n_quotes != 1 else ''} ready to review.", "success")
        return redirect(url_for("shipper.booking_detail", ref=b.ref))

    sa_cities = sorted(SA_CITIES)
    # Allow safe pre-fill from rebook links without creating a booking yet.
    # This keeps rebook as: duplicate shipment details -> user reviews/edits -> request quotes.
    prefill = request.args.to_dict(flat=True) if request.args else {}
    return render_template("shipper/shipment.html",
        title="New Shipment",
        shipper=shipper, address_book=address_book, suppliers=suppliers,
        form=prefill,
        cities=sa_cities,
        settings={"volumetricDivisor": 4000})


@shipper_bp.route("/bookings/<ref>")
@shipper_required
def booking_detail(ref):
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    quotes  = score_quotes(booking.quotes.filter_by(status="Pending").all())
    explanations = {q.id: explain_rank(q) for q in quotes}
    return render_template("shipper/booking_detail.html",
        title=booking.ref,
        booking=booking_to_v19(booking),
        booking_obj=booking,
        quotes=[quote_to_v19(q) for q in quotes],
        explanations=explanations, shipper=shipper)


@shipper_bp.route("/bookings/<ref>/rate", methods=["POST"])
@shipper_required
def rate_booking(ref):
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()

    if booking.status != "Delivered":
        flash("Rating is only available once the delivery is completed.", "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))

    if booking.rating:
        flash("You've already rated this delivery.", "info")
        return redirect(url_for("shipper.booking_detail", ref=ref))

    try:
        stars = int(request.form.get("stars", 0))
    except ValueError:
        stars = 0
    if not (1 <= stars <= 5):
        flash("Please select a star rating.", "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))

    booking.rating         = stars
    booking.rating_comment = request.form.get("comment", "").strip()
    booking.rated_at       = datetime.utcnow()
    db.session.commit()

    # Roll the rating into the supplier's running average score
    if booking.supplier:
        sup = booking.supplier
        delivered_ratings = [b.rating for b in sup.bookings.filter(
            Booking.rating.isnot(None)).all()]
        if delivered_ratings:
            sup.score = round(sum(delivered_ratings) / len(delivered_ratings), 2)
            db.session.commit()

    flash("Thanks for your feedback!", "success")
    return redirect(url_for("shipper.booking_detail", ref=ref))


@shipper_bp.route("/bookings/<ref>/report-event", methods=["POST"])
@shipper_required
def report_booking_event(ref):
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()

    event_type = request.form.get("eventType", "")
    valid_types = {
        "delay_1h":      "Delayed < 1 hour",
        "delay_3h":      "Delayed 1-3 hours",
        "delay_over3h":  "Delayed > 3 hours",
        "dc_miss":       "DC slot missed",
        "damage":        "Cargo damage",
    }
    if event_type not in valid_types:
        flash("Please select a valid event type.", "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))

    event = BookingStatusEvent(
        booking_id = booking.id,
        status     = event_type,
        note       = valid_types[event_type],
        actor      = current_user.full_name,
    )
    db.session.add(event)
    db.session.commit()

    # Notify admin so they're aware of service issues being logged
    admins = User.query.filter_by(role="admin").all()
    for adm in admins:
        push_notification(adm.id,
            f"Service event logged - {booking.ref}",
            f"{shipper.company_name or current_user.full_name} reported: {valid_types[event_type]}",
            type="warning", ref_type="booking", ref_id=booking.ref)

    flash("Event reported. This has been logged against the supplier's performance record.", "success")
    return redirect(url_for("shipper.booking_detail", ref=ref))


@shipper_bp.route("/bookings/<ref>/accept-quote/<int:quote_id>", methods=["POST"])
@shipper_required
def accept_quote(ref, quote_id):
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    quote   = Quote.query.get_or_404(quote_id)

    ok, reason = can_select_quote(booking, quote)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))

    # Accept this quote, reject others
    for q in booking.quotes:
        q.status = "Rejected"
    quote.status = "Accepted"

    booking.supplier_id      = quote.supplier_id
    booking.accepted_quote_id = quote.id
    booking.quoted_value     = quote.amount
    booking.calculate_platform_fee()

    # Generate the operational order and cargo label immediately after price acceptance.
    # The shipper now has an official order/label/QR package to prepare the goods;
    # payment method decides whether it moves straight to supplier acceptance or EFT payment.
    invoice = apply_shipper_payment_terms(booking)
    ensure_shipper_order(booking, current_user.full_name)

    # Status event
    event = BookingStatusEvent(booking_id=booking.id, status=booking.status,
                                note=f"Quote selected by shipper: R{quote.amount:,.2f}. Order and label generated. Payment terms: {invoice.status}.",
                                actor=current_user.full_name)
    db.session.add(event)

    db.session.commit()
    log_action(current_user.id, "ACCEPT_QUOTE", "Booking", ref,
               f"Quote ID {quote_id}, amount R{quote.amount:,.2f}")
    if invoice.status == "Account Terms":
        if booking.supplier:
            push_notification(booking.supplier.user_id,
                f"Action required - Booking {booking.ref}",
                f"Order released on account terms for {booking.route}. Accept the job and assign a driver/vehicle within the SLA window.",
                type="warning", ref_type="booking", ref_id=booking.ref)
        flash(f"Quote selected. Order generated and released on 30-day account terms. Supplier acceptance is now pending.", "success")
        return redirect(url_for("shipper.booking_detail", ref=ref))
    flash(f"Quote selected. Order and label generated. Please pay invoice {invoice.invoice_number} to release it to the supplier.", "success")
    return redirect(url_for("shipper.pay_booking", ref=ref))


@shipper_bp.route("/bookings/<ref>/cancel", methods=["POST"])
@shipper_required
def cancel_booking(ref):
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    if booking.status in ("Collected", "In Transit", "Delivered"):
        flash("Cannot cancel a booking that is already in transit or delivered.", "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))
    reason = request.form.get("reason", "Cancelled by shipper")
    booking.status = "Cancelled"
    event = BookingStatusEvent(booking_id=booking.id, status="Cancelled",
                                note=reason, actor=current_user.full_name)
    db.session.add(event)
    db.session.commit()
    flash(f"Booking {ref} cancelled.", "info")
    return redirect(url_for("shipper.bookings"))


@shipper_bp.route("/bookings/<ref>/reorder")
@shipper_required
def reorder(ref):
    shipper = get_shipper()
    original = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()

    # Rebook must never copy financial/operational state or create a confirmed booking.
    # It only pre-fills the New Shipment form, then the user reviews/edits and requests fresh quotes.
    # Render the form directly instead of redirecting with a very long query string, because
    # browsers/proxies can truncate long addresses and make the button appear broken.
    prefill = {
        "rebookFrom": original.ref,
        "collectionAddress": original.collection_address or "",
        "pickupCity": original.collection_city or "",
        "deliveryAddress": original.delivery_address or "",
        "dropoffCity": original.delivery_city or "",
        "commodityType": original.commodity or "",
        "pieces": original.pieces or 1,
        "quantity": original.pieces or 1,
        "weightPerItem": original.weight_per_item_kg or "",
        "weight_per_item": original.weight_per_item_kg or "",
        "vehicleType": original.vehicle_type_req or "",
        "pickupContactName": original.collection_contact or "",
        "pickupContactPhone": original.collection_phone or "",
        "dropoffContactName": original.delivery_contact or "",
        "dropoffContactPhone": original.delivery_phone or "",
        "destinationType": original.destination_type or "Door-to-door",
        "unitType": "pallets" if (original.pieces or 0) > 1 else "pieces",
    }
    flash(f"Rebooking {original.ref}: details copied into a new shipment request. Review, adjust, then request fresh quotes.", "info")
    address_book = shipper.address_book.all()
    suppliers = SupplierProfile.query.filter_by(status="Active").all()
    return render_template("shipper/shipment.html",
        title=f"Reorder {original.ref}",
        shipper=shipper, address_book=address_book, suppliers=suppliers,
        form=prefill, cities=sorted(SA_CITIES), settings={"volumetricDivisor": 4000})


@shipper_bp.route("/bookings/<ref>/reorder/confirm", methods=["POST"])
@shipper_required
def reorder_confirm(ref):
    # Legacy endpoint kept for old forms. Redirect to safe prefill flow instead
    # of creating a booking directly.
    return redirect(url_for("shipper.reorder", ref=ref))


# ── Analytics & Intelligence ──────────────────────────────────────────────────

@shipper_bp.route("/analytics")
@shipper_required
def analytics():
    shipper  = get_shipper()
    all_bk   = shipper.bookings.all()
    delivered= [b for b in all_bk if b.status == "Delivered"]

    # ── Monthly spend buckets ────────────────────────────────────
    monthly_buckets = {}
    for b in delivered:
        key = b.created_at.strftime("%b %Y") if b.created_at else "Unknown"
        if key not in monthly_buckets:
            monthly_buckets[key] = {"total": 0, "routes": {}, "commodities": {}, "savings": 0}
        val = b.quoted_value or 0
        monthly_buckets[key]["total"] += val
        monthly_buckets[key]["savings"] += round(val * 0.175, 2)   # broker equiv saving
        r = b.route or "Unknown"
        monthly_buckets[key]["routes"][r] = monthly_buckets[key]["routes"].get(r, 0) + val
        c = b.commodity or "General"
        monthly_buckets[key]["commodities"][c] = monthly_buckets[key]["commodities"].get(c, 0) + val

    monthly_labels = list(monthly_buckets.keys())[-6:]
    monthly_values = [monthly_buckets[k]["total"] for k in monthly_labels]
    monthly_savings= [monthly_buckets[k]["savings"] for k in monthly_labels]

    # ── Route analysis ───────────────────────────────────────────
    route_spend = {}
    for b in delivered:
        route_spend[b.route or "Unknown"] = route_spend.get(b.route or "Unknown", 0) + (b.quoted_value or 0)
    top_routes = sorted(route_spend.items(), key=lambda x: x[1], reverse=True)[:5]

    # ── On-time delivery rate ────────────────────────────────────
    on_time = sum(1 for b in delivered if b.delivered_at and b.collection_date
                  and b.delivered_at.date() <= b.collection_date + timedelta(days=1))
    on_time_rate = round((on_time / len(delivered) * 100), 1) if delivered else 0

    # ── Supplier analysis ────────────────────────────────────────
    supplier_counts = {}
    supplier_spend  = {}
    for b in delivered:
        sname = b.supplier.company_name if b.supplier else "Unknown"
        supplier_counts[sname] = supplier_counts.get(sname, 0) + 1
        supplier_spend[sname]  = supplier_spend.get(sname, 0) + (b.quoted_value or 0)
    top_supplier = max(supplier_counts, key=supplier_counts.get) if supplier_counts else "-"
    top_suppliers_list = sorted(supplier_spend.items(), key=lambda x: x[1], reverse=True)[:5]

    # ── Cost metrics ─────────────────────────────────────────────
    total_spend     = sum(b.quoted_value or 0 for b in delivered)
    broker_equiv    = round(total_spend * 1.175, 2)
    total_savings   = round(broker_equiv - total_spend, 2)
    total_bookings  = len(delivered)
    pending_count   = sum(1 for b in all_bk if b.status in ("Pending Quotes","Confirmed","In Transit"))
    avg_cost        = total_spend / total_bookings if total_bookings else 0
    cpk_list        = [b.quoted_value / b.distance_km for b in delivered if b.distance_km and b.quoted_value]
    avg_cpk         = sum(cpk_list) / len(cpk_list) if cpk_list else 0

    # ── GIT coverage rate ────────────────────────────────────────
    git_covered = sum(1 for b in all_bk if b.git_insurance)
    git_rate    = round(git_covered / len(all_bk) * 100, 1) if all_bk else 0

    # ── Fragile shipments ────────────────────────────────────────
    fragile_count = sum(1 for b in all_bk if b.is_fragile)

    spend_monthly = [
        {
            "month":       monthly_labels[i],
            "total":       monthly_buckets[monthly_labels[i]]["total"],
            "savings":     monthly_buckets[monthly_labels[i]]["savings"],
            "routes":      monthly_buckets[monthly_labels[i]]["routes"],
            "commodities": monthly_buckets[monthly_labels[i]]["commodities"],
            "topSupplier": top_supplier,
        }
        for i in range(len(monthly_labels))
    ]
    if not spend_monthly:
        spend_monthly = [{"month": "-", "total": 0, "savings": 0, "routes": {},
                          "commodities": {}, "topSupplier": "-"}]
    spend = {"monthly": spend_monthly}

    return render_template("shipper/analytics.html",
        title="Spend Analytics",
        shipper=shipper,
        bookings=[booking_to_v19(b) for b in delivered],
        spend=spend,
        monthly_labels=monthly_labels, monthly_values=monthly_values,
        monthly_savings=monthly_savings,
        top_routes=top_routes, top_suppliers_list=top_suppliers_list,
        total_spend=total_spend, broker_equiv=broker_equiv, total_savings=total_savings,
        total_bookings=total_bookings, pending_count=pending_count,
        avg_cost=avg_cost, avg_cpk=avg_cpk,
        on_time_rate=on_time_rate,
        git_rate=git_rate, fragile_count=fragile_count)


@shipper_bp.route("/analytics/export")
@shipper_required
def analytics_export():
    shipper  = get_shipper()
    bookings = shipper.bookings.filter_by(status="Delivered").all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Booking Ref","Route","Commodity","Date","Status","Value (R)","Platform Fee (R)","Distance (km)"])
    for b in bookings:
        writer.writerow([
            b.ref, b.route, b.commodity,
            b.created_at.strftime("%Y-%m-%d") if b.created_at else "",
            b.status, f"{b.quoted_value:.2f}", f"{b.platform_fee:.2f}",
            b.distance_km or ""
        ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.read().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"freightflow_spend_{date.today()}.csv"
    )


@shipper_bp.route("/health-score")
@shipper_required
def health_score():
    shipper = get_shipper()
    scores  = compute_health_score(shipper)
    return render_template("shipper/health_score.html",
        title="Health Score", shipper=shipper, **scores)


@shipper_bp.route("/ai-insights")
@shipper_required
def ai_insights():
    shipper  = get_shipper()
    bookings = shipper.bookings.all()
    scores   = compute_health_score(shipper)

    insights = []
    total_spend = sum(b.quoted_value or 0 for b in bookings)

    if total_spend > 0:
        insights.append({
            "icon":"Chart","type":"trend","impact":"neutral",
            "title": f"Total logistics spend: R{total_spend:,.0f}",
            "detail": f"Across {len(bookings)} bookings. Your average booking value is R{total_spend/len(bookings):,.0f}." if bookings else ""
        })

    # Supplier reliability
    supplier_scores = [(b.supplier.company_name, b.supplier.score) for b in bookings if b.supplier]
    if supplier_scores:
        worst = min(supplier_scores, key=lambda x: x[1])
        if worst[1] < 4.0:
            insights.append({
                "icon":"Warning","type":"risk","impact":"negative",
                "title": f"{worst[0]} has a below-average score ({worst[1]}/5.0)",
                "detail": "Consider switching suppliers for this route to improve your reliability score."
            })

    # Cost
    if scores["cost_efficiency"] > 85:
        insights.append({
            "icon":"Money","type":"opportunity","impact":"positive",
            "title": "Your cost efficiency is above platform average",
            "detail": "You're spending less per km than 72% of FreightFlow shippers. Keep using your preferred suppliers."
        })
    else:
        insights.append({
            "icon":"Tip","type":"opportunity","impact":"positive",
            "title": "Consolidating loads could reduce your per-km cost",
            "detail": "Combining partial loads on the same route could reduce cost per kg by up to 22%."
        })

    insights.append({
        "icon":"Forecast","type":"trend","impact":"neutral",
        "title": "Peak season approaching - July volumes typically increase 28%",
        "detail": "Based on historical platform data, July sees significantly higher freight demand. Book capacity early."
    })

    return render_template("shipper/ai_insights.html",
        title="AI Insights",
        shipper=shipper, insights=insights, scores=scores,
        spend=[], pct_change=0)


@shipper_bp.route("/opportunities")
@shipper_required
def opportunities():
    shipper  = get_shipper()
    bookings = shipper.bookings.all()

    # Generate opportunities based on real data
    opps = []
    route_counts = {}
    route_spend  = {}
    for b in bookings:
        if b.route:
            route_counts[b.route] = route_counts.get(b.route, 0) + 1
            route_spend[b.route]  = route_spend.get(b.route, 0) + (b.quoted_value or 0)

    for route, count in route_counts.items():
        if count >= 3:
            annual_est = route_spend[route] * 2  # extrapolate
            saving = round(annual_est * 0.14)
            opps.append({
                "title": "Preferred supplier contract",
                "route": route,
                "detail": f"You ship this route {count} times. A preferred rate agreement could unlock 14% savings.",
                "saving": f"R {saving:,}",
                "savingPct": 14,
                "urgency": "High",
                "action": "Book new shipment"
            })

    if not opps:
        opps = [
            {"title":"Book more frequently to unlock contract pricing","route":"All routes",
             "detail":"Suppliers offer preferential rates to high-volume shippers. Book 5+ loads to start negotiating.","saving":"R 0","savingPct":0,"urgency":"Low","action":"New booking"}
        ]

    total_savings = sum(int(o["saving"].replace("R ","").replace(",","")) for o in opps)
    return render_template("shipper/opportunities.html",
        title="Opportunities",
        shipper=shipper, opportunities=opps, total_savings=total_savings)


@shipper_bp.route("/risk")
@shipper_required
def risk():
    shipper = get_shipper()
    active_bookings = shipper.bookings.filter(
        Booking.status.in_(["Confirmed","Driver Assigned","Collected","In Transit"])
    ).all()
    booking_risks = []
    for b in active_bookings:
        if b.supplier:
            sc = b.supplier.score
            if sc >= 4.5:   risk, risk_pct, color = "Low",    8,  "#27ae60"
            elif sc >= 3.5: risk, risk_pct, color = "Medium", 28, "#e67e22"
            else:           risk, risk_pct, color = "High",   62, "#c0392b"
        else:
            risk, risk_pct, color = "Medium", 35, "#e67e22"
        factors = []
        if b.supplier and b.supplier.score < 4.0:
            factors.append("Supplier score below platform average")
        if b.status == "In Transit":
            factors.append("Long-haul active transit")
        if b.destination_type == "DC":
            factors.append("DC slot delivery - time-critical")
        booking_risks.append({
            "ref":           b.ref,
            "route":         b.route or "",
            "shipper":       b.shipper.user.full_name if b.shipper and b.shipper.user else "-",
            "supplier":      b.supplier.company_name if b.supplier else "-",
            "status":        b.status,
            "value":         b.quoted_value or 0,
            "supplierScore": b.supplier.score if b.supplier else 0,
            "risk":          risk,
            "risk_pct":      risk_pct,
            "color":         color,
            "factors":       factors,
        })
    return render_template("shipper/risk.html",
        title="Risk Tracker",
        shipper=shipper, booking_risks=booking_risks)


@shipper_bp.route("/ai-assistant")
@shipper_required
def ai_assistant():
    shipper = get_shipper()
    return render_template("shipper/ai_assistant.html",
        title="AI Assistant", shipper=shipper, bookings=[], suppliers=[])


@shipper_bp.route("/address-book")
@shipper_required
def address_book():
    shipper   = get_shipper()
    addresses = shipper.address_book.order_by(AddressBook.label).all()
    return render_template("shipper/address_book.html",
        title="Address Book",
        shipper=shipper, addresses=addresses)


@shipper_bp.route("/address-book/add", methods=["POST"])
@shipper_required
def add_address():
    shipper = get_shipper()
    addr = AddressBook(
        shipper_id=shipper.id,
        label        = request.form.get("label",""),
        address      = request.form.get("address",""),
        city         = request.form.get("city",""),
        contact_name = request.form.get("contact_name",""),
        contact_phone= request.form.get("contact_phone",""),
        type         = request.form.get("type","Delivery"),
    )
    db.session.add(addr)
    db.session.commit()
    flash("Address saved to address book.", "success")
    return redirect(url_for("shipper.address_book"))


@shipper_bp.route("/address-book/<int:addr_id>/delete", methods=["POST"])
@shipper_required
def delete_address(addr_id):
    shipper = get_shipper()
    addr    = AddressBook.query.filter_by(id=addr_id, shipper_id=shipper.id).first_or_404()
    db.session.delete(addr)
    db.session.commit()
    flash("Address removed.", "info")
    return redirect(url_for("shipper.address_book"))


# ── Notifications ─────────────────────────────────────────────────────────────

@shipper_bp.route("/notifications")
@shipper_required
def notifications():
    notes = current_user.notifications.order_by(
        Notification.created_at.desc()).limit(50).all()
    # Mark all as read
    current_user.notifications.filter_by(is_read=False).update({"is_read": True})
    db.session.commit()
    return render_template("shipper/reports.html",
        title="Notifications", notifications=notes)


# ── Complaints ────────────────────────────────────────────────────────────────

from app.models import Complaint  # local import to avoid circular at top

@shipper_bp.route("/complaints")
@shipper_required
def complaints():
    shipper = get_shipper()
    all_complaints = shipper.complaints.order_by(Complaint.created_at.desc()).all()
    return render_template("shipper/complaints.html",
        title="My Complaints", complaints=all_complaints)


@shipper_bp.route("/complaints/new", methods=["GET", "POST"])
@shipper_required
def complaint_new():
    shipper  = get_shipper()
    bookings = shipper.bookings.order_by(Booking.created_at.desc()).limit(50).all()
    selected_ref = request.args.get("ref", "")

    if request.method == "POST":
        booking_ref  = request.form.get("bookingRef", "").strip()
        category     = request.form.get("category", "").strip()
        priority     = request.form.get("priority", "Normal").strip()
        description  = request.form.get("description", "").strip()
        dispute_amount_raw = request.form.get("disputeAmount", "").strip()
        dispute_amount = float(dispute_amount_raw) if dispute_amount_raw else None

        if not category or not description:
            flash("Please fill in all required fields.", "error")
            return render_template("shipper/complaint_new.html",
                title="New Complaint", bookings=bookings, selected_ref=selected_ref)

        # Resolve booking & supplier
        booking  = Booking.query.filter_by(ref=booking_ref).first() if booking_ref else None
        supplier = booking.supplier if booking else None

        c = Complaint(
            shipper_id  = shipper.id,
            booking_id  = booking.id if booking else None,
            supplier_id = supplier.id if supplier else None,
            category    = category,
            priority    = priority,
            description = description,
            dispute_amount = dispute_amount,
            status      = "Submitted",
        )
        c.generate_ref()
        db.session.add(c)
        db.session.flush()   # get id before commit

        # Handle file uploads (store filenames only)
        files = request.files.getlist("evidence")
        saved = []
        import os, werkzeug.utils
        upload_dir = os.path.join("app", "static", "complaint_evidence")
        os.makedirs(upload_dir, exist_ok=True)
        for f in files:
            if f and f.filename:
                fname = werkzeug.utils.secure_filename(f"{c.ref}_{f.filename}")
                f.save(os.path.join(upload_dir, fname))
                saved.append(fname)
        if saved:
            c.evidence_files = ",".join(saved)

        # Seed the conversation thread (matches v15: shipper's opening message + system ack)
        from app.models import ComplaintMessage
        db.session.add(ComplaintMessage(
            complaint_id=c.id, sender_role="shipper",
            sender_name=shipper.company_name or current_user.full_name, text=description))
        db.session.add(ComplaintMessage(
            complaint_id=c.id, sender_role="system", sender_name="FreightFlow System",
            text=f"Report {c.ref} received. Priority: {priority}. Our support team will respond shortly."))

        db.session.commit()

        # Notify all admins
        admins = User.query.filter_by(role="admin").all()
        for adm in admins:
            push_notification(adm.id,
                f"New complaint {c.ref}",
                f"{shipper.company_name or current_user.full_name} filed a {c.priority} complaint: {c.category}",
                type="warning", ref_type="complaint", ref_id=c.ref)

        flash(f"Complaint {c.ref} submitted. Our support team will review it shortly.", "success")
        return redirect(url_for("shipper.complaint_detail", ref=c.ref))

    return render_template("shipper/complaint_new.html",
        title="New Complaint", bookings=bookings, selected_ref=selected_ref)


@shipper_bp.route("/complaints/<ref>")
@shipper_required
def complaint_detail(ref):
    shipper = get_shipper()
    c = Complaint.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    return render_template("shipper/complaint_detail.html", title=f"Complaint {ref}", complaint=c)


@shipper_bp.route("/complaints/<ref>/reply", methods=["POST"])
@shipper_required
def complaint_reply(ref):
    from app.models import ComplaintMessage
    shipper = get_shipper()
    c = Complaint.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()

    msg = request.form.get("message", "").strip()
    if msg:
        db.session.add(ComplaintMessage(
            complaint_id=c.id, sender_role="shipper",
            sender_name=shipper.company_name or current_user.full_name, text=msg))
        db.session.commit()

        # Notify admins / assigned agent
        if c.assigned_agent_id:
            push_notification(c.assigned_agent_id,
                f"New message on complaint {c.ref}",
                f"{shipper.company_name or current_user.full_name} replied: \"{msg[:80]}\"",
                type="info", ref_type="complaint", ref_id=c.ref)
        else:
            for adm in User.query.filter_by(role="admin").all():
                push_notification(adm.id,
                    f"New message on complaint {c.ref}",
                    f"{shipper.company_name or current_user.full_name} replied: \"{msg[:80]}\"",
                    type="info", ref_type="complaint", ref_id=c.ref)

        flash("Message sent.", "success")
    return redirect(url_for("shipper.complaint_detail", ref=ref))


# ── Kargo AI Chatbot ──────────────────────────────────────────────────────────

def _build_kargo_system_prompt(shipper):
    """Build the live-context system prompt for Kargo - shared by both endpoints."""
    from app.models import Complaint
    recent_bookings = shipper.bookings.order_by(
        Booking.created_at.desc()).limit(10).all()

    booking_lines = []
    for b in recent_bookings:
        booking_lines.append(
            f"  - {b.ref} | {b.route or 'N/A'} | Status: {b.status} "
            f"| Supplier: {b.supplier.company_name if b.supplier else 'Unassigned'} "
            f"| Value: R{b.quoted_value or 0:,.0f} "
            f"| Collection: {b.collection_date or 'TBC'}"
        )

    recent_complaints = shipper.complaints.order_by(
        Complaint.created_at.desc()).limit(5).all()

    complaint_lines = []
    for c in recent_complaints:
        complaint_lines.append(
            f"  - {c.ref} | {c.category} | Priority: {c.priority} "
            f"| Status: {c.status} "
            f"| Booking: {c.booking.ref if c.booking else 'N/A'}"
        )

    company = shipper.company_name or current_user.full_name
    return f"""You are Kargo, a friendly and knowledgeable AI freight assistant for FreightFlow Nexus - a South African freight marketplace.

You are speaking with {current_user.full_name} from {company}.

YOUR ROLE:
- Help the shipper understand the status of their bookings and shipments
- Help them raise, track, or understand their complaints
- Explain what each booking or complaint status means
- Give clear, practical advice about next steps
- Keep responses concise and conversational - this is a chat bubble, not a report
- Use South African context (ZAR, local cities, SA freight norms)
- Never make up booking details - only refer to what's listed below

SHIPPER'S LIVE BOOKING DATA (last 10):
{chr(10).join(booking_lines) if booking_lines else '  No bookings found.'}

SHIPPER'S LIVE COMPLAINT DATA (last 5):
{chr(10).join(complaint_lines) if complaint_lines else '  No complaints filed.'}

COMPLAINT WORKFLOW (explain this when relevant):
1. Shipper submits complaint -> status: Submitted
2. Admin reviews it internally -> status: Under Admin Review
3. Admin forwards to supplier -> status: Forwarded to Supplier
4. Supplier responds -> status: Supplier Responded
5. Admin resolves -> status: Resolved
Suppliers never see a complaint until admin explicitly forwards it.

BOOKING STATUSES:
Pending Quotes -> Quotes Received -> Confirmed -> Driver Assigned -> Collected -> In Transit -> Approaching Destination -> Delivered -> Cancelled

If asked something outside freight/bookings/complaints, politely steer back.
Keep responses under 120 words unless the shipper asks for detail."""


def _call_kargo_api(system_prompt, messages):
    """Provider-agnostic Kargo assistant.

    The demo no longer depends on a third-party AI API key.
    Kargo answers are grounded in the same FreightFlow AI engine used for quote
    ranking, equipment-fit scoring, proximity, risk and health scoring.
    """
    shipper = get_shipper()
    last_user_message = ""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            last_user_message = m.get("content", "")
            break
    return assistant_answer(shipper, last_user_message or "Give me my FreightFlow summary")

@shipper_bp.route("/kargo-chat", methods=["POST"])
@shipper_required
def kargo_chat():
    """Kargo bubble in the sidebar - receives {messages:[...]} returns {reply:...}"""
    from flask import jsonify
    data     = request.get_json(silent=True) or {}
    messages = [{"role": m["role"], "content": m["content"]} for m in data.get("messages", [])]
    shipper  = get_shipper()
    reply    = _call_kargo_api(_build_kargo_system_prompt(shipper), messages)
    return jsonify({"reply": reply})


@shipper_bp.route("/api/ai-assistant", methods=["POST"])
@shipper_required
def api_ai_assistant():
    """Full AI Assistant page - receives {question:...} returns {answer:...}"""
    from flask import jsonify
    data     = request.get_json(silent=True) or {}
    question = data.get("question", "").strip()
    if not question:
        return jsonify({"answer": "Please ask me something."})
    shipper  = get_shipper()
    messages = [{"role": "user", "content": question}]
    answer   = _call_kargo_api(_build_kargo_system_prompt(shipper), messages)
    return jsonify({"answer": answer})


# ═══════════════════════════════════════════════════════════════════════════
# INVOICES
# ═══════════════════════════════════════════════════════════════════════════

@shipper_bp.route("/invoices")
@shipper_required
def invoices():
    shipper = get_shipper()
    booking_ids = [b.id for b in shipper.bookings.all()]
    invoice_list = Invoice.query.filter(Invoice.booking_id.in_(booking_ids))\
        .order_by(Invoice.created_at.desc()).all() if booking_ids else []
    return render_template("shipper/invoices.html", title="Invoices", invoices=invoice_list)


# ═══════════════════════════════════════════════════════════════════════════
# PAYMENTS (pay a booking's invoice)
# ═══════════════════════════════════════════════════════════════════════════

@shipper_bp.route("/booking/<ref>/pay", methods=["GET", "POST"])
@shipper_required
def pay_booking(ref):
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    invoice = booking.invoice

    if not booking.accepted_quote_id:
        flash("Select a supplier quote before payment.", "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))

    if not invoice:
        flash("No invoice found for this booking yet. Select a quote first so the system can generate an invoice.", "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))

    if request.method == "POST":
        ok, reason = can_pay_booking(booking)
        if not ok:
            flash(reason, "error" if invoice.status != "Paid" else "info")
            return redirect(url_for("shipper.booking_detail", ref=ref))

        invoice.status = "Paid"
        invoice.paid_at = datetime.utcnow()
        booking.status = "Pending Supplier Acceptance"
        deadline = start_supplier_response_sla(booking)
        log_finance_event(booking, "Escrow Funded",
            "Shipper payment received by FreightFlow. Funds are held by the platform pending supplier acceptance, delivery, POD, and finance payout release.",
            current_user.full_name)
        db.session.add(BookingStatusEvent(booking_id=booking.id, status="Pending Supplier Acceptance",
            note=f"Payment received by platform. Supplier must accept and assign a driver within {SUPPLIER_SLA_HOURS} hours before the booking can proceed. Deadline: {deadline:%Y-%m-%d %H:%M} UTC.", actor=current_user.full_name))
        shipper.total_spend = (shipper.total_spend or 0) + (booking.quoted_value or 0)
        db.session.commit()

        if booking.supplier:
            push_notification(booking.supplier.user_id,
                f"Action required - Booking {booking.ref}",
                f"Payment has been received for {booking.route}. You have {SUPPLIER_SLA_HOURS} hours to accept and assign a driver, otherwise the booking will expire.",
                type="warning", ref_type="booking", ref_id=booking.ref)

        push_notification(current_user.id,
            f"Payment confirmed - {booking.ref}",
            f"Your payment of R{invoice.total_amount:,.2f} has been settled successfully.",
            type="success", ref_type="booking", ref_id=booking.ref)

        flash(f"Payment of R{invoice.total_amount:,.2f} confirmed. Supplier has {SUPPLIER_SLA_HOURS} hours to accept and assign a driver.", "success")
        return redirect(url_for("shipper.booking_detail", ref=ref))

    return render_template("shipper/payment.html", title="Pay invoice",
        booking=booking, invoice=invoice)


# ═══════════════════════════════════════════════════════════════════════════
# COMPANY PROFILE
# ═══════════════════════════════════════════════════════════════════════════

@shipper_bp.route("/profile", methods=["GET", "POST"])
@shipper_required
def profile():
    shipper = get_shipper()

    if request.method == "POST":
        shipper.company_name = request.form.get("company_name", "").strip()
        shipper.vat_number   = request.form.get("vat_number", "").strip()
        shipper.industry     = request.form.get("industry", "").strip()
        shipper.address      = request.form.get("address", "").strip()
        shipper.city         = request.form.get("city", "").strip()
        shipper.province     = request.form.get("province", "").strip()
        current_user.phone   = request.form.get("phone", "").strip()
        db.session.commit()
        flash("Profile updated.", "success")
        return redirect(url_for("shipper.profile"))

    docs = shipper.documents.order_by(ShipperDocument.uploaded_at.desc()).all()
    return render_template("shipper/profile.html", title="Company profile",
        shipper=shipper, documents=docs)


@shipper_bp.route("/profile/documents/<int:doc_id>/download")
@shipper_required
def download_profile_doc(doc_id):
    shipper = get_shipper()
    doc = ShipperDocument.query.get_or_404(doc_id)
    if doc.shipper_id != shipper.id:
        flash("Access denied.", "error")
        return redirect(url_for("shipper.profile"))
    filename = doc.filename
    if filename:
        path = os.path.abspath(os.path.join("app", "static", "shipper_documents", filename))
        if os.path.exists(path):
            return send_file(path, as_attachment=False, download_name=filename)
    content = f"FreightFlow Nexus shipper document\nDocument: {doc.name}\nStatus: {doc.status}\nFilename: {filename or 'Not uploaded'}\n"
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/plain", as_attachment=False, download_name=f"shipper-document-{doc.id}.txt")

@shipper_bp.route("/invoices/<int:invoice_id>")
@shipper_bp.route("/payments/<int:invoice_id>/invoice")
@shipper_required
def view_invoice(invoice_id):
    shipper = get_shipper()
    invoice = Invoice.query.get_or_404(invoice_id)
    if not invoice.booking or invoice.booking.shipper_id != shipper.id:
        flash("Access denied.", "error")
        return redirect(url_for("shipper.invoices"))
    return render_template("shipper/invoice_detail.html", title=f"Invoice {invoice.invoice_number}", invoice=invoice, booking=invoice.booking, shipper=shipper)

@shipper_bp.route("/invoices/<int:invoice_id>/download")
@shipper_required
def download_invoice(invoice_id):
    shipper = get_shipper()
    invoice = Invoice.query.get_or_404(invoice_id)
    if not invoice.booking or invoice.booking.shipper_id != shipper.id:
        flash("Access denied.", "error")
        return redirect(url_for("shipper.invoices"))
    content = (
        "FreightFlow Nexus Tax Invoice\n"
        f"Invoice: {invoice.invoice_number}\n"
        f"Booking: {invoice.booking.ref}\n"
        f"Route: {invoice.booking.route}\n"
        f"Status: {invoice.status}\n"
        f"Amount: R{(invoice.amount or 0):,.2f}\n"
        f"VAT: R{(invoice.vat_amount or 0):,.2f}\n"
        f"Total: R{(invoice.total_amount or 0):,.2f}\n"
    )
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/plain", as_attachment=False, download_name=f"{invoice.invoice_number}.txt")

@shipper_bp.route("/profile/upload-doc", methods=["POST"])
@shipper_required
def upload_profile_doc():
    shipper = get_shipper()
    name = request.form.get("name", "").strip()
    f = request.files.get("file")

    if not name:
        flash("Please specify the document type.", "error")
        return redirect(url_for("shipper.profile"))

    filename = None
    if f and f.filename:
        import os, werkzeug.utils
        upload_dir = os.path.join("app", "static", "shipper_documents")
        os.makedirs(upload_dir, exist_ok=True)
        filename = werkzeug.utils.secure_filename(f"{shipper.id}_{name}_{f.filename}")
        f.save(os.path.join(upload_dir, filename))

    db.session.add(ShipperDocument(shipper_id=shipper.id, name=name,
                                    status="Pending review", filename=filename))
    db.session.commit()
    flash(f"{name} uploaded and submitted for review.", "success")
    return redirect(url_for("shipper.profile"))


# ═══════════════════════════════════════════════════════════════════════════
# REALLOCATION (reassign a booking to a different supplier)
# ═══════════════════════════════════════════════════════════════════════════

@shipper_bp.route("/booking/<ref>/reallocation")
@shipper_required
def reallocation(ref):
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()

    ok, reason = can_reallocate(booking)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))

    other_quotes = booking.quotes.filter(Quote.supplier_id != booking.supplier_id, Quote.booking_id == booking.id).all()
    return render_template("shipper/reallocation.html", title="Reallocate booking",
        booking=booking, other_quotes=other_quotes)


@shipper_bp.route("/booking/<ref>/reallocation/confirm/<int:quote_id>", methods=["POST"])
@shipper_required
def reallocation_confirm(ref, quote_id):
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    new_quote = Quote.query.get_or_404(quote_id)

    ok, reason = can_reallocate(booking)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))
    if new_quote.booking_id != booking.id:
        flash("Cannot reallocate using a quote from another booking.", "error")
        return redirect(url_for("shipper.reallocation", ref=ref))
    if new_quote.status not in ("Pending", "Submitted", "Quoted", None):
        flash("This quote is no longer available for reallocation.", "error")
        return redirect(url_for("shipper.reallocation", ref=ref))

    old_supplier = booking.supplier
    if old_supplier:
        push_notification(old_supplier.user_id,
            f"Booking reassigned - {booking.ref}",
            "This booking has been reassigned to a different supplier by the shipper.",
            type="warning", ref_type="booking", ref_id=booking.ref)

    for q in booking.quotes:
        q.status = "Rejected"
    new_quote.status = "Accepted"
    booking.supplier_id = new_quote.supplier_id
    booking.accepted_quote_id = new_quote.id
    booking.quoted_value = new_quote.amount
    booking.calculate_platform_fee()
    # If already paid, supplier must accept again. If not paid, payment is required first.
    booking.status = "Pending Supplier Acceptance" if booking.invoice and booking.invoice.status == "Paid" else "Awaiting Payment"
    db.session.add(BookingStatusEvent(booking_id=booking.id, status="Pending Supplier Acceptance",
        note=f"Reallocated to {new_quote.supplier.company_name} by shipper", actor=current_user.full_name))
    db.session.commit()

    push_notification(new_quote.supplier.user_id,
        f"New booking - {booking.ref}",
        f"You've been assigned booking {booking.ref}. Please accept and assign a driver within {SUPPLIER_SLA_HOURS} hours.",
        type="warning", ref_type="booking", ref_id=booking.ref)

    flash(f"Booking reassigned to {new_quote.supplier.company_name}.", "success")
    return redirect(url_for("shipper.booking_detail", ref=ref))


# ═══════════════════════════════════════════════════════════════════════════
# WAYBILL
# ═══════════════════════════════════════════════════════════════════════════

@shipper_bp.route("/booking/<ref>/waybill")
@shipper_required
def waybill(ref):
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    ok, reason = can_view_waybill(booking)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))
    return render_template("shipper/waybill.html", title=f"Waybill - {ref}", booking=booking)


@shipper_bp.route("/booking/<ref>/label")
@shipper_required
def shipment_label(ref):
    """Printable customer-facing cargo label.

    This unlocks as soon as a shipper selects a quote/supplier. It is for
    sticking onto pallets/parcels before collection, while the full waybill
    remains the operational/legal document after supplier acceptance.
    """
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    if not booking.accepted_quote_id or not booking.supplier_id:
        flash("Shipment label unlocks after you select a supplier quote.", "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))
    return render_template("shipper/label.html", title=f"Shipment Label - {ref}", booking=booking, shipper=shipper)

# ═══════════════════════════════════════════════════════════════════════════
# GIT INSURANCE
# ═══════════════════════════════════════════════════════════════════════════

@shipper_bp.route("/booking/<ref>/git-insurance", methods=["GET", "POST"])
@shipper_required
def git_insurance(ref):
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    existing = booking.git_insurance

    if request.method == "POST":
        cargo_value = float(request.form.get("cargo_value", 0) or 0)
        if cargo_value <= 0:
            flash("Please enter a valid cargo value.", "error")
            return redirect(url_for("shipper.git_insurance", ref=ref))

        if existing:
            flash("GIT insurance already active for this booking.", "info")
            return redirect(url_for("shipper.booking_detail", ref=ref))

        git = GITInsurance(booking_id=booking.id, cargo_value=cargo_value)
        git.calculate_premium()
        db.session.add(git)
        db.session.flush()
        git.generate_policy_ref()

        # POD token is deliberately NOT auto-generated by insurance.
        # It is only allowed after supplier acceptance + driver dispatch.

        db.session.commit()
        log_action(current_user.id, "GIT_ISSUED", "Booking", ref,
                   f"GIT R{cargo_value:,.0f} - policy {git.policy_ref}")
        push_notification(current_user.id,
            f"GIT Insurance active - {ref}",
            f"Policy {git.policy_ref} covers R{cargo_value:,.0f} cargo. Premium: R{git.premium_amount:,.2f}.",
            type="success", ref_type="booking", ref_id=ref)
        flash(f"GIT Insurance issued - Policy ref: {git.policy_ref}", "success")
        return redirect(url_for("shipper.booking_detail", ref=ref))

    # GET - show form
    return render_template("shipper/git_insurance.html",
        title="GIT Insurance",
        booking=booking_to_v19(booking),
        existing=existing)


# ═══════════════════════════════════════════════════════════════════════════
# QR POD SCAN (public endpoint - no login required, token-based)
# ═══════════════════════════════════════════════════════════════════════════

@shipper_bp.route("/pod/scan/<token>", methods=["GET", "POST"])
def pod_scan(token):
    """Driver scans QR code at delivery gate - triggers Delivered + invoice."""
    from app.models import PODToken, Invoice, BookingStatusEvent
    pod = PODToken.query.filter_by(token=token).first_or_404()
    booking = pod.booking

    if pod.scanned:
        return render_template("shipper/pod_already_scanned.html",
            booking=booking_to_v19(booking))

    if request.method == "POST":
        ok, reason = can_scan_pod(booking)
        if not ok:
            return render_template("shipper/pod_scan.html", booking=booking_to_v19(booking), token=token, error=reason)
        scanner_name = request.form.get("scanner_name", "Driver").strip() or "Driver"
        now = datetime.utcnow()

        # Mark POD scanned
        pod.scanned    = True
        pod.scanned_at = now
        pod.scanned_by = scanner_name

        # Update booking to Delivered
        booking.status       = "Delivered"
        booking.delivered_at = now
        booking.pod_signed   = True
        booking.pod_signed_at= now

        db.session.add(BookingStatusEvent(
            booking_id=booking.id, status="Delivered",
            note=f"POD scanned by {scanner_name} via QR code", actor=scanner_name))

        # Auto-generate invoice if not exists
        if not booking.invoice:
            import secrets as _sec
            inv = Invoice(booking_id=booking.id)
            # Set a placeholder invoice_number (NOT NULL) before flush, then finalise
            inv.invoice_number = f"INV-{datetime.utcnow().year}-{_sec.token_hex(3).upper()}"
            amount     = booking.quoted_value or 0
            vat        = round(amount * 0.15, 2)
            inv.amount      = amount
            inv.vat_amount  = vat
            inv.total_amount= round(amount + vat, 2)
            from datetime import timedelta
            inv.due_date = (now + timedelta(days=30)).date()
            db.session.add(inv)
            db.session.flush()
            # Now self.id is available - overwrite with canonical format
            inv.invoice_number = f"INV-{datetime.utcnow().year}-{inv.id:05d}"

        # Notify shipper finance contact + shipper user
        shipper = booking.shipper
        msg = (f"QR POD scanned for {booking.ref} - "
               f"status set to Delivered. Invoice ready for processing.")
        push_notification(shipper.user_id, f"POD Confirmed - {booking.ref}", msg,
                          type="success", ref_type="booking", ref_id=booking.ref)

        # If finance contact email stored - in real app would send email here
        finance_email = shipper.finance_contact_email or ""

        db.session.commit()
        log_action(None, "POD_SCANNED", "Booking", booking.ref,
                   f"Scanned by {scanner_name}")
        return render_template("shipper/pod_confirmed.html",
            booking=booking_to_v19(booking),
            scanner=scanner_name,
            finance_email=finance_email)

    # GET - show scan confirmation form
    return render_template("shipper/pod_scan.html",
        booking=booking_to_v19(booking),
        token=token)


# ═══════════════════════════════════════════════════════════════════════════
# GENERATE / GET POD TOKEN for a booking (shipper triggers from booking detail)
# ═══════════════════════════════════════════════════════════════════════════

@shipper_bp.route("/booking/<ref>/generate-pod", methods=["POST"])
@shipper_required
def generate_pod(ref):
    import secrets
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    ok, reason = can_generate_pod_token(booking)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("shipper.booking_detail", ref=ref))
    if not booking.pod_token:
        tok = PODToken(booking_id=booking.id, token=secrets.token_urlsafe(32))
        db.session.add(tok)
        db.session.commit()
        flash("QR POD token generated. Print the waybill to share the QR code.", "success")
    else:
        flash("POD token already exists for this booking.", "info")
    return redirect(url_for("shipper.booking_detail", ref=ref))


# ═══════════════════════════════════════════════════════════════════════════
# SHIPPER FINANCE CONTACT (update from profile page)
# ═══════════════════════════════════════════════════════════════════════════

@shipper_bp.route("/profile/finance-contact", methods=["POST"])
@shipper_required
def update_finance_contact():
    shipper = get_shipper()
    shipper.finance_contact_name  = request.form.get("finance_contact_name", "").strip()
    shipper.finance_contact_email = request.form.get("finance_contact_email", "").strip()
    db.session.commit()
    flash("Finance contact updated.", "success")
    return redirect(url_for("shipper.profile"))

# ── Demo-flow aliases from the original v15 prototype ────────────────────────
@shipper_bp.route('/shipment', methods=['GET', 'POST'])
@shipper_required
def legacy_shipment():
    return new_booking()

@shipper_bp.route('/quotes')
@shipper_required
def legacy_quotes():
    # Quote comparison now happens inside each booking detail page. Send the
    # user to the newest booking that is still collecting quotes, otherwise the
    # filtered booking list is the clearest next step.
    shipper = get_shipper()
    booking = shipper.bookings.filter(Booking.status.in_(['Pending Quotes', 'Quotes Received']))\
        .order_by(Booking.created_at.desc()).first()
    if booking:
        return redirect(url_for('shipper.booking_detail', ref=booking.ref))
    return redirect(url_for('shipper.bookings', status='Pending Quotes'))

@shipper_bp.route('/payments')
@shipper_required
def legacy_payments():
    # Keep the v15-style Payments URL as a real page, not a redirect, so buttons
    # and browser refresh behave consistently during demos.
    shipper = get_shipper()
    booking_ids = [b.id for b in shipper.bookings.all()]
    invoice_list = Invoice.query.filter(Invoice.booking_id.in_(booking_ids))\
        .order_by(Invoice.created_at.desc()).all() if booking_ids else []
    return render_template("shipper/invoices.html", title="Payments", invoices=invoice_list, page_heading="Payments")

@shipper_bp.route('/booking/<ref>')
@shipper_required
def legacy_booking_detail(ref):
    return redirect(url_for('shipper.booking_detail', ref=ref))

@shipper_bp.route('/booking/<ref>/track')
@shipper_required
def legacy_booking_track(ref):
    return redirect(url_for('shipper.booking_detail', ref=ref))


# ─────────────────────────────────────────────────────────────────────────────
# Button-level repair: legacy reports alias
# ─────────────────────────────────────────────────────────────────────────────
@shipper_bp.route("/reports")
@login_required
def reports():
    # The old demo used /shipper/reports. The functional complaint centre now
    # lives under /shipper/complaints, so keep the button route alive.
    return redirect(url_for("shipper.complaints"))

# ── Location Access Request ──────────────────────────────────────────────────
@shipper_bp.route('/bookings/<ref>/request-location', methods=['POST'])
@shipper_required
def request_driver_location(ref):
    shipper = get_shipper()
    booking = Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    reason = (request.form.get('reason') or '').strip() or 'High-value or time-sensitive shipment'
    if not booking.supplier_id:
        flash('A supplier must be selected before location access can be requested.', 'error')
        return redirect(url_for('shipper.booking_detail', ref=ref))
    booking.location_access_requested = True
    booking.location_access_reason = reason[:200]
    booking.location_access_status = 'Pending'
    db.session.add(BookingStatusEvent(booking_id=booking.id, status='Location Access Requested',
        note=booking.location_access_reason, actor=current_user.full_name))
    if booking.supplier and booking.supplier.user_id:
        push_notification(booking.supplier.user_id, f'Location request - {booking.ref}',
            f'Shipper requested live driver location access. Reason: {booking.location_access_reason}',
            type='warning', ref_type='booking', ref_id=booking.ref)
    db.session.commit()
    flash('Location request sent to supplier for approval.', 'success')
    return redirect(url_for('shipper.booking_detail', ref=ref))


# Shipment document hub shared with the shipper
@shipper_bp.route("/bookings/<ref>/documents")
@shipper_required
def shipment_documents(ref):
    from app.services.evidence_pack import pod_files, pod_meta
    shipper=get_shipper()
    booking=Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    po=PurchaseOrder.query.filter_by(booking_id=booking.id).order_by(PurchaseOrder.created_at.desc()).first()
    ok, reason=can_view_waybill(booking)
    return render_template("shipper/documents.html", title=f"Documents - {ref}", booking=booking, po=po, pod_files=pod_files(booking), pod_meta=pod_meta(booking), waybill_ok=ok, waybill_reason=reason)

@shipper_bp.route("/bookings/<ref>/documents/service-pack")
@shipper_required
def shipment_service_pack(ref):
    from app.services.evidence_pack import build_service_pack
    shipper=get_shipper()
    booking=Booking.query.filter_by(ref=ref, shipper_id=shipper.id).first_or_404()
    po=PurchaseOrder.query.filter_by(booking_id=booking.id).order_by(PurchaseOrder.created_at.desc()).first()
    return send_file(build_service_pack(booking,po),mimetype="application/zip",as_attachment=True,download_name=f"{booking.ref}-proof-of-service-pack.zip")

@shipper_bp.route("/bookings/<ref>/service-pack.pdf")
@shipper_required
def shipment_service_pack_pdf(ref):
    import io
    from app.services.evidence_pack import combined_service_pack_pdf
    booking=Booking.query.filter_by(ref=ref,shipper_id=current_user.shipper_profile.id).first_or_404()
    po=PurchaseOrder.query.filter_by(booking_id=booking.id).first()
    return send_file(io.BytesIO(combined_service_pack_pdf(booking,po)),mimetype="application/pdf",as_attachment=True,download_name=f"{booking.ref}-complete-service-pack.pdf")

@shipper_bp.route("/bookings/<ref>/documents/pod/<filename>")
@shipper_required
def shipment_pod_download(ref, filename):
    from werkzeug.utils import secure_filename
    from app.services.evidence_pack import pod_files, POD_DIR
    shipper=get_shipper(); booking=Booking.query.filter_by(ref=ref,shipper_id=shipper.id).first_or_404()
    safe=secure_filename(filename)
    if safe not in pod_files(booking):
        flash("POD document not found.","error"); return redirect(url_for("shipper.shipment_documents",ref=ref))
    return send_file(os.path.abspath(os.path.join(POD_DIR,safe)),as_attachment=True,download_name=safe)
