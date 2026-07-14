"""Public routes - landing page, public tracking"""
from flask import Blueprint, render_template, jsonify, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import Booking, Notification, SupplierProfile
from app.services.ai_engine import assistant_answer

public_bp = Blueprint("public", __name__)
api_bp    = Blueprint("api", __name__)


@public_bp.route("/")
def index():
    return render_template("public/landing.html")


@public_bp.route("/track/<ref>")
def public_track(ref):
    booking = Booking.query.filter_by(ref=ref).first()
    if not booking:
        return render_template("public_tracking.html", booking=None, events=[], ref=ref), 404
    events  = booking.status_events
    return render_template("public_tracking.html", booking=booking, events=events)


@public_bp.route("/onboarding")
def onboarding():
    return render_template("onboarding.html")


@public_bp.route("/onboarding/submit", methods=["POST"])
def onboarding_submit():
    """Demo supplier onboarding submit endpoint.

    The onboarding page is a guided demo flow, so this endpoint records a
    successful submission-style interaction without requiring a real supplier
    account to be created yet. This prevents the final submit button from
    posting to a missing route during demos.
    """
    flash("Supplier application submitted for compliance review. Demo onboarding complete.", "success")
    return render_template("onboarding_success.html")


# ── JSON API ──────────────────────────────────────────────────────────────────

@api_bp.route("/notifications/unread-count")
@login_required
def notifications_count():
    count = current_user.notifications.filter_by(is_read=False).count()
    return jsonify({"count": count})


@api_bp.route("/notifications/mark-read", methods=["POST"])
@login_required
def mark_notifications_read():
    from app.models import db
    current_user.notifications.filter_by(is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify({"ok": True})


@api_bp.route("/ai-assistant", methods=["POST"])
@login_required
def ai_assistant():
    """FreightFlow AI / Kargo assistant powered by the shared Kargo engine."""
    question = (request.json or {}).get("question", "")
    if current_user.role == "shipper" and current_user.shipper_profile:
        return jsonify({"answer": assistant_answer(current_user.shipper_profile, question)})
    return jsonify({"answer": "Kargo AI currently supports shipper shipment intelligence, quote explanations, equipment recommendations and delivery risk summaries."})

@api_bp.route("/booking/<ref>/events")
@login_required
def booking_events(ref):
    booking = Booking.query.filter_by(ref=ref).first_or_404()
    events = [{"status": e.status, "note": e.note, "time": str(e.created_at)[:16]}
              for e in booking.status_events]
    return jsonify(events)


# ─── QR Scan - collection and delivery confirmation (no login) ────────────────
@public_bp.route("/scan/<ref>/<event>", methods=["GET", "POST"])
def qr_scan(ref, event):
    """Standalone page for drivers to confirm collection or delivery via QR scan."""
    from app.models import Booking, BookingStatusEvent, db
    from app.services.notifications import push_notification
    from app.services.order_workflow import mark_ready_for_supplier_invoice
    from datetime import datetime

    booking = Booking.query.filter_by(ref=ref).first()
    if not booking:
        return render_template("scan.html", booking=None, ref=ref, event=event)

    from app.services.v19_adapter import booking_to_v19
    b = booking_to_v19(booking)

    if request.method == "POST":
        now = datetime.utcnow()
        actor = request.form.get("actor", "Driver").strip() or "Driver"

        if event == "collect" and booking.status not in ("In Transit", "Delivered"):
            booking.status       = "Collected"
            booking.collected_at = now
            db.session.add(BookingStatusEvent(
                booking_id=booking.id, status="Collected",
                note=f"Collection confirmed via QR scan by {actor}", actor=actor))
            push_notification(booking.shipper.user_id,
                f"Cargo collected - {ref}",
                f"Driver confirmed collection. Shipment is now Collected and ready for in-transit updates.",
                type="success", ref_type="booking", ref_id=ref)
            db.session.commit()
            return render_template("scan.html", booking=b, ref=ref, event=event, done=True,
                message="Collection confirmed. Cargo has been collected.")

        elif event == "deliver" and booking.status != "Delivered":
            booking.status       = "Delivered"
            booking.delivered_at = now
            booking.pod_signed   = True
            booking.pod_signed_at= now
            db.session.add(BookingStatusEvent(
                booking_id=booking.id, status="Delivered",
                note=f"Delivery confirmed via QR scan by {actor}. Physical POD/supporting documents may be uploaded from the driver app.", actor=actor))
            mark_ready_for_supplier_invoice(booking, actor)
            # Auto-generate invoice
            from app.models import Invoice
            import secrets as _sec
            if not booking.invoice:
                inv = Invoice(booking_id=booking.id)
                inv.invoice_number = f"INV-{now.year}-{_sec.token_hex(3).upper()}"
                amt = booking.quoted_value or 0
                vat = round(amt * 0.15, 2)
                inv.amount = amt; inv.vat_amount = vat
                inv.total_amount = round(amt + vat, 2)
                from datetime import timedelta
                inv.due_date = (now + timedelta(days=30)).date()
                db.session.add(inv)
                db.session.flush()
                inv.invoice_number = f"INV-{now.year}-{inv.id:05d}"
            push_notification(booking.shipper.user_id,
                f"Delivered - {ref}",
                f"Delivery confirmed. Invoice generated.",
                type="success", ref_type="booking", ref_id=ref)
            db.session.commit()
            return render_template("scan.html", booking=b, ref=ref, event=event, done=True,
                message="Delivery confirmed. Invoice generated and shipper notified.")

        return render_template("scan.html", booking=b, ref=ref, event=event,
            done=True, message="Already recorded.")

    return render_template("scan.html", booking=b, ref=ref, event=event, done=False)


@api_bp.route("/driver/simulate-scan", methods=["POST"])
def driver_simulate_scan():
    """Demo driver-app scan endpoint that writes simulated collection/POD events to DB.

    The standalone mobile demo cannot rely on a SocketIO server in every deployment,
    so the visible simulate buttons POST here first. Socket broadcasts can still be
    layered on top later, but this keeps shipper/supplier portals in sync now.
    """
    from datetime import datetime
    from app.models import Booking, BookingStatusEvent, db
    from app.services.notifications import push_notification

    data = request.get_json(silent=True) or request.form
    ref = (data.get("booking_ref") or data.get("ref") or "").strip()
    event = (data.get("event") or "").strip()
    actor = (data.get("actor") or data.get("driver_name") or "Driver app demo").strip() or "Driver app demo"

    booking = Booking.query.filter_by(ref=ref).first()
    if not booking:
        return jsonify({"ok": False, "error": f"Booking {ref or '-'} was not found in this deployment database."}), 404

    now = datetime.utcnow()
    message = None

    if event == "collect":
        if booking.status not in ("Driver Assigned", "Collected"):
            return jsonify({"ok": False, "error": f"Collection can only be confirmed from Driver Assigned status. Current status: {booking.status}."}), 409
        booking.status = "Collected"
        booking.collected_at = booking.collected_at or now
        message = "Collection confirmed. Booking is now Collected."

    elif event == "deliver":
        if booking.status not in ("Collected", "In Transit", "Approaching Destination"):
            return jsonify({"ok": False, "error": f"Delivery can only be confirmed after collection/in-transit. Current status: {booking.status}."}), 409
        booking.status = "Delivered"
        booking.delivered_at = booking.delivered_at or now
        booking.pod_signed = True
        booking.pod_signed_at = booking.pod_signed_at or now
        if booking.driver:
            booking.driver.status = "Active"
        if booking.vehicle:
            booking.vehicle.availability = "Available"
        message = "Delivery confirmed. Booking is now Delivered and POD is signed."

    elif event == "pod":
        if booking.status != "Delivered":
            return jsonify({"ok": False, "error": "Capture/attach POD after delivery confirmation."}), 409
        booking.pod_signed = True
        booking.pod_signed_at = booking.pod_signed_at or now
        message = "POD captured and linked to the delivered booking."

    else:
        return jsonify({"ok": False, "error": "Unknown scan event."}), 400

    db.session.add(BookingStatusEvent(
        booking_id=booking.id, status=booking.status,
        note=f"{message} Triggered from standalone driver app.", actor=actor))
    if booking.shipper and booking.shipper.user_id:
        push_notification(booking.shipper.user_id, f"Shipment update - {booking.ref}", message,
                          type="success", ref_type="booking", ref_id=booking.ref)
    db.session.commit()
    return jsonify({"ok": True, "status": booking.status, "message": message})

# ── Legacy/demo flow aliases from the original v15 prototype ─────────────────
# These keep the first demo's URLs working while v21 uses the cleaner blueprint
# structure. They are intentionally thin redirects so the product flow is not
# split across duplicate pages.
from flask import redirect, url_for

@public_bp.route('/landing')
def legacy_landing():
    return redirect(url_for('public.index'))

@public_bp.route('/scan')
def legacy_scan_start():
    sample = Booking.query.order_by(Booking.created_at.desc()).first()
    if sample:
        return redirect(url_for('public.qr_scan', ref=sample.ref, event='collect'))
    return render_template('scan.html', booking=None, ref='DEMO', event='collect')

@api_bp.route('/calculate', methods=['POST'])
def calculate_shipment():
    """Compatibility API from the demo: estimate CBM, chargeable weight and rough vehicle fit."""
    payload = request.get_json(silent=True) or request.form or {}
    def num(name, default=0):
        try:
            return float(payload.get(name, default) or default)
        except (TypeError, ValueError):
            return float(default)
    pieces = max(num('pieces', 1), 1)
    length_cm = num('length_cm') or num('length') or 0
    width_cm = num('width_cm') or num('width') or 0
    height_cm = num('height_cm') or num('height') or 0
    weight_each = num('weight_per_item') or num('weight') or num('weight_kg') or 0
    cbm = round((length_cm * width_cm * height_cm * pieces) / 1_000_000, 3)
    actual_weight = round(weight_each * pieces, 2)
    volumetric_weight = round(cbm * 333, 2)
    chargeable_weight = max(actual_weight, volumetric_weight)
    if chargeable_weight <= 1000 and cbm <= 6:
        vehicle = '1-Ton Van / Bakkie'
    elif chargeable_weight <= 4000 and cbm <= 28:
        vehicle = '4-Ton Truck'
    elif chargeable_weight <= 8000 and cbm <= 48:
        vehicle = '8-Ton Rigid / Curtainsider'
    elif chargeable_weight <= 22000 and cbm <= 80:
        vehicle = 'Horse & Trailer'
    else:
        vehicle = 'Superlink / Specialist Quote'
    return jsonify({
        'ok': True,
        'pieces': pieces,
        'cbm': cbm,
        'actual_weight_kg': actual_weight,
        'volumetric_weight_kg': volumetric_weight,
        'chargeable_weight_kg': chargeable_weight,
        'recommended_vehicle': vehicle,
    })

@public_bp.route('/login', methods=['GET', 'POST'])
def legacy_login_alias():
    return redirect(url_for('auth.login'))

@public_bp.route('/register', methods=['GET', 'POST'])
def legacy_register_alias():
    return redirect(url_for('auth.register'))

@public_bp.route('/logout')
def legacy_logout_alias():
    return redirect(url_for('auth.logout'))
