"""Driver blueprint"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime
import os
from werkzeug.utils import secure_filename

from app.models import db, Booking, Driver, BookingStatusEvent, DeliveryEvidence, DeliveryEvidenceFile
from app.services.notifications import push_notification
from app.services.lifecycle import can_transition, can_view_waybill
from app.services.order_workflow import mark_ready_for_supplier_invoice

driver_bp = Blueprint("driver", __name__)


def _save_delivery_evidence(booking, driver, form, files):
    """Validate and persist the complete POD evidence checklist."""
    receiver = (form.get("pod_recipient_name") or "").strip()
    notes = (form.get("pod_note") or "").strip()
    lat_raw = (form.get("delivery_lat") or "").strip()
    lng_raw = (form.get("delivery_lng") or "").strip()
    pod_uploads = [f for f in files.getlist("pod_documents") if f and f.filename]
    main_pod = files.get("pod_photo")
    if main_pod and main_pod.filename:
        pod_uploads.insert(0, main_pod)
    receiver_signature = files.get("receiver_signature")
    driver_signature = files.get("driver_signature")

    missing = []
    if not receiver: missing.append("receiver name")
    if not lat_raw or not lng_raw: missing.append("delivery GPS")
    if not pod_uploads: missing.append("POD photo or signed document")
    if not receiver_signature or not receiver_signature.filename: missing.append("receiver signature")
    if not driver_signature or not driver_signature.filename: missing.append("driver signature")
    if missing:
        return None, "Complete the required delivery evidence: " + ", ".join(missing) + "."
    try:
        lat, lng = float(lat_raw), float(lng_raw)
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError
    except ValueError:
        return None, "Delivery GPS coordinates are invalid. Capture GPS again."

    upload_dir = os.path.abspath(os.path.join("app", "static", "pod_photos"))
    os.makedirs(upload_dir, exist_ok=True)
    evidence = booking.delivery_evidence or DeliveryEvidence(booking=booking)
    evidence.receiver_name = receiver
    evidence.delivery_notes = notes
    evidence.latitude = lat
    evidence.longitude = lng
    evidence.delivered_at = datetime.utcnow()
    evidence.completed_by_user_id = current_user.id
    if evidence.id:
        for old in list(evidence.files):
            try:
                if os.path.isfile(old.file_path): os.remove(old.file_path)
            except OSError:
                pass
            db.session.delete(old)
    db.session.add(evidence)
    db.session.flush()

    groups = [("pod", pod_uploads), ("receiver_signature", [receiver_signature]), ("driver_signature", [driver_signature])]
    saved = []
    allowed = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
    for file_type, uploads in groups:
        for index, upload in enumerate(uploads):
            original = secure_filename(upload.filename)
            ext = os.path.splitext(original)[1].lower()
            if ext not in allowed:
                return None, f"Unsupported evidence file type: {ext or original}. Use PDF, PNG, JPG or WEBP."
            effective_type = "delivery_photo" if file_type == "pod" and index > 0 else file_type
            stored = secure_filename(f"{booking.ref}_{effective_type}_{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{original}")
            absolute = os.path.join(upload_dir, stored)
            upload.save(absolute)
            db.session.add(DeliveryEvidenceFile(evidence=evidence, file_type=effective_type, file_path=absolute, original_filename=original, stored_filename=stored, mime_type=upload.mimetype))
            saved.append(stored)

    booking.gps_lat, booking.gps_lng = lat, lng
    booking.gps_updated_at = datetime.utcnow()
    return evidence, None

def driver_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != "driver":
            flash("Access denied.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated

@driver_bp.route("/")
@driver_required
def dashboard():
    from app.services.v19_adapter import driver_to_v19, booking_to_v19
    driver   = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    active   = driver.bookings.filter(
                Booking.status.in_(["Driver Assigned","Collected","In Transit","Approaching Destination"])).all()
    completed = driver.bookings.filter_by(status="Delivered").count()
    return render_template("driver/dashboard.html",
        driver=driver_to_v19(driver),
        bookings=[booking_to_v19(b) for b in active],
        active_bookings=active, completed=completed)

@driver_bp.route("/bookings/<ref>/update", methods=["POST"])
@driver_required
def update_status(ref):
    driver  = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    booking = Booking.query.filter_by(ref=ref, driver_id=driver.id).first_or_404()
    new_status = request.form.get("status")
    note       = request.form.get("note","")
    valid      = ["Collected","In Transit","Approaching Destination","Delivered"]
    if new_status in valid:
        if new_status == "Delivered":
            flash("Complete delivery from the Driver App so POD, signatures and GPS are captured together.", "warning")
            return redirect(url_for("driver.app_job", ref=ref))
        ok, reason = can_transition(booking, new_status)
        if not ok:
            flash(reason, "error")
            return redirect(url_for("driver.dashboard"))
        if new_status == "Delivered" and not booking.pod_signed:
            pod_name = (request.form.get("pod_recipient_name") or "").strip()
            pod_note = (request.form.get("pod_note") or "").strip()
            pod_confirmed = request.form.get("pod_confirmed") == "1"
            if not pod_name or not pod_confirmed:
                flash("Delivery requires POD confirmation: enter the receiver name and tick the POD confirmation box.", "error")
                return redirect(url_for("driver.booking_detail", ref=ref))
            booking.pod_signed = True
            booking.pod_signed_at = datetime.utcnow()
            uploaded = []
            upload_dir = os.path.join("app", "static", "pod_photos")
            os.makedirs(upload_dir, exist_ok=True)
            all_files = []
            pod_file = request.files.get("pod_photo")
            if pod_file and pod_file.filename:
                all_files.append(pod_file)
            all_files.extend([f for f in request.files.getlist("pod_documents") if f and f.filename])
            receiver_sig = request.files.get("receiver_signature")
            driver_sig = request.files.get("driver_signature")
            if receiver_sig and receiver_sig.filename: all_files.append(receiver_sig)
            if driver_sig and driver_sig.filename: all_files.append(driver_sig)
            for f in all_files:
                ext_name = secure_filename(f.filename)
                filename = secure_filename(f"{booking.ref}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{ext_name}")
                f.save(os.path.join(upload_dir, filename))
                uploaded.append(filename)
                if f is receiver_sig:
                    note = (note + " | " if note else "") + f"Receiver signature file: {filename}"
                if f is driver_sig:
                    note = (note + " | " if note else "") + f"Driver signature file: {filename}"
            if uploaded:
                note = (note + " | " if note else "") + "Proof documents uploaded: " + ", ".join(uploaded)
            lat = request.form.get("delivery_lat", "").strip()
            lng = request.form.get("delivery_lng", "").strip()
            try:
                if lat and lng:
                    booking.gps_lat, booking.gps_lng = float(lat), float(lng)
                    booking.gps_updated_at = datetime.utcnow()
                    note = (note + " | " if note else "") + f"Delivery GPS: {booking.gps_lat:.6f}, {booking.gps_lng:.6f}"
            except ValueError:
                pass
            if pod_note:
                note = (note + " | " if note else "") + f"POD note: {pod_note}"
            note = (note + " | " if note else "") + f"POD signed by {pod_name}"

        booking.status = new_status
        if new_status == "Delivered":
            booking.delivered_at = datetime.utcnow()
            driver.total_trips  += 1
            driver.status = "Active"
            if booking.vehicle:
                booking.vehicle.availability = "Available"
            mark_ready_for_supplier_invoice(booking, current_user.full_name)
        event = BookingStatusEvent(booking_id=booking.id, status=new_status,
                                    note=note, actor=current_user.full_name)
        db.session.add(event)
        push_notification(booking.shipper.user_id, f"Shipment update - {booking.ref}",
                          f"Your shipment status: {new_status}." + (" POD proof has been captured and is available from booking details." if new_status == "Delivered" else ""),
                          type="info", ref_type="booking", ref_id=booking.ref)
        if new_status == "Delivered" and booking.supplier:
            push_notification(booking.supplier.user_id, f"POD ready - {booking.ref}",
                              "Delivery is complete. Download the POD and service pack from Documents, then submit your invoice.",
                              type="success", ref_type="booking", ref_id=booking.ref)
        db.session.commit()
        flash(f"Status updated to {new_status}.", "success")
    return redirect(url_for("driver.dashboard"))


@driver_bp.route("/booking/<ref>")
@driver_required
def booking_detail(ref):
    from app.services.v19_adapter import booking_to_v19
    driver  = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    booking = Booking.query.filter_by(ref=ref, driver_id=driver.id).first_or_404()
    return render_template("driver/booking_detail.html", title=booking.ref,
        booking=booking_to_v19(booking), driver=driver)


@driver_bp.route("/profile")
@driver_required
def profile():
    from app.services.v19_adapter import driver_to_v19
    driver = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    return render_template("driver/profile.html", title="My profile", driver=driver_to_v19(driver))


@driver_bp.route("/chat")
@driver_required
def chat():
    from app.models import ChatMessage
    driver = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    messages = ChatMessage.query.filter_by(driver_id=driver.id).order_by(ChatMessage.created_at).all()
    # mark supplier->driver messages read
    ChatMessage.query.filter_by(driver_id=driver.id, sender_role="supplier", is_read=False)\
        .update({"is_read": True})
    db.session.commit()
    return render_template("driver/chat.html", title="Chat with dispatcher", driver=driver, messages=messages)


@driver_bp.route("/chat/send", methods=["POST"])
@driver_required
def chat_send():
    from app.models import ChatMessage
    driver = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    text = request.form.get("text", "").strip()
    issue_type = request.form.get("issue_type", "").strip() or None
    if text:
        db.session.add(ChatMessage(supplier_id=driver.supplier_id, driver_id=driver.id,
                                    sender_role="driver", text=text, issue_type=issue_type))
        db.session.commit()
        push_notification(driver.supplier.user_id,
            f"Message from {driver.name}" + (f" [{issue_type}]" if issue_type else ""), text,
            type="warning" if issue_type else "info", ref_type="driver_chat", ref_id=str(driver.id))
    return redirect(url_for("driver.chat"))


# ─── GPS update endpoint (called by driver app every 30s) ────────────────────
@driver_bp.route("/gps/update", methods=["POST"])
@driver_required
def gps_update():
    from app.models import Booking
    data = request.get_json(silent=True) or {}
    lat  = data.get("lat")
    lng  = data.get("lng")
    ref  = data.get("ref")
    if not (lat and lng and ref):
        return jsonify({"ok": False, "error": "Missing lat/lng/ref"}), 400

    driver = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    booking = Booking.query.filter_by(ref=ref, driver_id=driver.id).first()
    if not booking:
        return jsonify({"ok": False, "error": "Booking not found for this driver"}), 404
    if booking.status not in ("Driver Assigned", "Collected", "In Transit", "Approaching Destination"):
        return jsonify({"ok": False, "error": "GPS updates are only allowed for active assigned trips"}), 403

    booking.gps_lat        = float(lat)
    booking.gps_lng        = float(lng)
    booking.gps_updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True})


# ─── Live tracking JSON (polled by shipper tracking page) ────────────────────
@driver_bp.route("/gps/<ref>")
def gps_position(ref):
    """Public GPS endpoint - no login required, only returns position if In Transit."""
    from app.models import Booking
    booking = Booking.query.filter_by(ref=ref).first()
    if not booking or booking.status not in ("In Transit", "Collected", "Approaching Destination"):
        return jsonify({"tracking": False})
    if getattr(booking, "location_access_status", "Not Requested") != "Approved":
        return jsonify({"tracking": False, "requiresApproval": True, "status": booking.status})
    return jsonify({
        "tracking":    True,
        "ref":         booking.ref,
        "status":      booking.status,
        "lat":         booking.gps_lat,
        "lng":         booking.gps_lng,
        "updatedAt":   booking.gps_updated_at.strftime("%H:%M:%S") if booking.gps_updated_at else None,
        "driver":      booking.driver.name if booking.driver else "-",
        "vehicle":     booking.vehicle.reg_number if booking.vehicle else "-",
        "destination": booking.delivery_city or "",
    })

# ─── Driver PWA demo app ─────────────────────────────────────────────────────
@driver_bp.route('/app')
@driver_required
def app_home():
    """Phone-first driver PWA home screen."""
    from app.services.v19_adapter import driver_to_v19, booking_to_v19
    driver = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    active = driver.bookings.filter(
        Booking.status.in_(['Driver Assigned', 'Collected', 'In Transit', 'Approaching Destination'])
    ).order_by(Booking.collection_date.asc(), Booking.created_at.desc()).all()
    completed_today = driver.bookings.filter_by(status='Delivered').count()
    return render_template('driver/pwa_app.html', title='Driver App',
        driver=driver_to_v19(driver),
        jobs=[booking_to_v19(b) for b in active],
        completed_today=completed_today)


@driver_bp.route('/app/job/<ref>')
@driver_required
def app_job(ref):
    from app.services.v19_adapter import booking_to_v19, driver_to_v19
    driver = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    booking = Booking.query.filter_by(ref=ref, driver_id=driver.id).first_or_404()
    return render_template('driver/pwa_job.html', title=f'Driver Job {booking.ref}',
        driver=driver_to_v19(driver), booking=booking_to_v19(booking))


@driver_bp.route('/app/job/<ref>/collect', methods=['POST'])
@driver_required
def app_collect(ref):
    driver = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    booking = Booking.query.filter_by(ref=ref, driver_id=driver.id).first_or_404()
    ok, reason = can_transition(booking, 'Collected')
    if not ok:
        flash(reason, 'error')
        return redirect(url_for('driver.app_job', ref=ref))
    booking.status = 'Collected'
    booking.collected_at = datetime.utcnow()
    event = BookingStatusEvent(booking_id=booking.id, status='Collected',
        note='Collection QR scanned by driver app.', actor=current_user.full_name)
    db.session.add(event)
    push_notification(booking.shipper.user_id, f'Collected - {booking.ref}',
        f'{driver.name} has scanned the collection QR and collected your shipment.',
        type='success', ref_type='booking', ref_id=booking.ref)
    if booking.supplier and booking.supplier.user_id:
        push_notification(booking.supplier.user_id, f'Collected - {booking.ref}',
            f'{driver.name} collected the shipment.', type='info', ref_type='booking', ref_id=booking.ref)
    db.session.commit()
    flash('Collection confirmed from driver app.', 'success')
    return redirect(url_for('driver.app_job', ref=ref))


@driver_bp.route('/app/job/<ref>/transit', methods=['POST'])
@driver_required
def app_start_transit(ref):
    driver = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    booking = Booking.query.filter_by(ref=ref, driver_id=driver.id).first_or_404()
    ok, reason = can_transition(booking, 'In Transit')
    if not ok:
        flash(reason, 'error')
        return redirect(url_for('driver.app_job', ref=ref))
    booking.status = 'In Transit'
    db.session.add(BookingStatusEvent(booking_id=booking.id, status='In Transit',
        note='Driver started live trip tracking.', actor=current_user.full_name))
    push_notification(booking.shipper.user_id, f'In transit - {booking.ref}',
        'Your shipment is now in transit. Live milestones will update automatically.',
        type='info', ref_type='booking', ref_id=booking.ref)
    db.session.commit()
    flash('Trip started.', 'success')
    return redirect(url_for('driver.app_job', ref=ref))


@driver_bp.route('/app/job/<ref>/deliver', methods=['POST'])
@driver_required
def app_deliver(ref):
    driver = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    booking = Booking.query.filter_by(ref=ref, driver_id=driver.id).first_or_404()
    ok, reason = can_transition(booking, 'Delivered')
    if not ok:
        flash(reason, 'error')
        return redirect(url_for('driver.app_job', ref=ref))
    evidence, error = _save_delivery_evidence(booking, driver, request.form, request.files)
    if error:
        db.session.rollback()
        flash(error, 'error')
        return redirect(url_for('driver.app_job', ref=ref))

    booking.status = 'Delivered'
    booking.delivered_at = evidence.delivered_at
    booking.pod_signed = True
    booking.pod_signed_at = evidence.delivered_at
    driver.status = 'Active'
    driver.total_trips = (driver.total_trips or 0) + 1
    if booking.vehicle:
        booking.vehicle.availability = 'Available'
    note = (f'POD signed by {evidence.receiver_name} | POD note: {evidence.delivery_notes or "-"} | '
            f'Delivery GPS: {evidence.latitude:.6f}, {evidence.longitude:.6f} | Structured delivery evidence captured')
    db.session.add(BookingStatusEvent(booking_id=booking.id, status='Delivered', note=note, actor=current_user.full_name, lat=evidence.latitude, lng=evidence.longitude))
    mark_ready_for_supplier_invoice(booking, current_user.full_name)
    push_notification(booking.shipper.user_id, f'Delivered - {booking.ref}',
        f'POD captured by {driver.name}. Your complete Proof of Service Pack is ready in Documents.',
        type='success', ref_type='booking', ref_id=booking.ref)
    if booking.supplier and booking.supplier.user_id:
        push_notification(booking.supplier.user_id, f'POD and service pack ready - {booking.ref}',
            'Delivery evidence is complete. Download the service pack and submit your invoice.',
            type='success', ref_type='booking', ref_id=booking.ref)
    db.session.commit()
    flash('Delivery completed. POD, signatures, GPS and service pack are ready.', 'success')
    return redirect(url_for('driver.app_job', ref=ref))


@driver_bp.route('/app/job/<ref>/location', methods=['POST'])
@driver_required
def app_location_update(ref):
    driver = Driver.query.filter_by(user_id=current_user.id).first_or_404()
    booking = Booking.query.filter_by(ref=ref, driver_id=driver.id).first_or_404()
    lat = request.form.get('lat') or (request.get_json(silent=True) or {}).get('lat')
    lng = request.form.get('lng') or (request.get_json(silent=True) or {}).get('lng')
    if not lat or not lng:
        return jsonify({'ok': False, 'error': 'Missing GPS coordinates'}), 400
    booking.gps_lat = float(lat)
    booking.gps_lng = float(lng)
    booking.gps_updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'ok': True, 'ref': booking.ref})
