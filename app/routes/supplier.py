"""
Supplier blueprint - quote submission, dispatch, fleet, compliance.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime, date, timedelta
import os, io, zipfile, re

from app.models import (db, Booking, Quote, SupplierProfile, Driver,
                         Vehicle, BookingStatusEvent, AvailabilitySlot,
                         SupplierScoreHistory, User, ComplianceDocument,
                         DocumentRequest, RateCard, PurchaseOrder, ChatMessage, Invoice, PlatformSettings, Trailer, FleetAssignment, MaintenanceRecord, SupplierPlanningSettings)
from app.services.ai_engine import score_quotes
from app.services.dispatch_eligibility import eligible_dispatch_data, driver_is_available, vehicle_is_available, vehicle_fits_booking
from app.services.v19_adapter import booking_to_v19, quote_to_v19, driver_to_v19
from app.services.notifications import push_notification, notify_all_role
from app.services.audit import log_action
from app.services.lifecycle import can_submit_quote, supplier_can_accept, can_dispatch, can_transition, can_view_waybill, expire_supplier_response_if_needed, SUPPLIER_SLA_HOURS
from app.services.finance import ensure_supplier_purchase_order, can_supplier_upload_invoice, log_finance_event
from app.services.order_workflow import ensure_delivery_pod_token
from app.services.capacity_planner import capacity_snapshot, ensure_settings, return_load_matches

supplier_bp = Blueprint("supplier", __name__)


def supplier_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != "supplier":
            flash("Access denied.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def get_supplier():
    return SupplierProfile.query.filter_by(user_id=current_user.id).first_or_404()


# ── Dashboard ─────────────────────────────────────────────────────────────────

@supplier_bp.route("/")
@supplier_required
def dashboard():
    supplier = get_supplier()
    snap = capacity_snapshot(supplier)
    db.session.commit()
    active_bookings = supplier.bookings.filter(Booking.status.in_(["Pending Dispatch","Confirmed","Driver Assigned","Collected","In Transit"])).all()
    revenue = db.session.query(db.func.sum(Booking.supplier_payout)).filter_by(supplier_id=supplier.id).scalar() or 0
    return render_template("supplier/control_tower.html", title="Supplier Control Tower", supplier=supplier,
        snapshot=snap, active_bookings=active_bookings, revenue=revenue,
        pending_quotes=supplier.quotes.filter_by(status="Pending").count())


# ── Quotes ────────────────────────────────────────────────────────────────────

@supplier_bp.route("/quote-requests")
@supplier_required
def quote_requests():
    supplier = get_supplier()
    if supplier.status != "Active":
        flash("Your account is under review. You'll be able to submit quotes once approved.", "warning")
        return render_template("supplier/bookings.html",
            title="Quote Requests",
            supplier=supplier, bookings=[], quoted_refs=[])

    # All open bookings needing quotes
    bookings    = Booking.query.filter_by(status="Pending Quotes").order_by(
                    Booking.created_at.desc()).all()
    quoted_refs = {q.booking_id for q in supplier.quotes.all()}
    return render_template("supplier/bookings.html",
        title="Quote Requests",
        supplier=supplier,
        bookings=[booking_to_v19(b) for b in bookings],
        quoted_refs=quoted_refs)


@supplier_bp.route("/quote-requests/<int:booking_id>/submit", methods=["POST"])
@supplier_required
def submit_quote(booking_id):
    supplier = get_supplier()
    booking  = Booking.query.get_or_404(booking_id)

    ok, reason = can_submit_quote(booking)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("supplier.quote_requests"))

    # Check not already quoted
    existing = Quote.query.filter_by(booking_id=booking_id,
                                      supplier_id=supplier.id).first()
    if existing:
        flash("You have already submitted a quote for this booking.", "warning")
        return redirect(url_for("supplier.quote_requests"))

    amount       = float(request.form.get("amount", 0))
    transit_days = int(request.form.get("transit_days", 1))
    notes        = request.form.get("notes", "")

    if amount <= 0:
        flash("Quote amount must be greater than zero.", "error")
        return redirect(url_for("supplier.quote_requests"))

    q = Quote(booking_id=booking_id, supplier_id=supplier.id,
              amount=amount, transit_days=transit_days, notes=notes)
    db.session.add(q)
    booking.status = "Quotes Received"

    # Notify shipper
    push_notification(booking.shipper.user_id,
                      f"New quote received for {booking.ref}",
                      f"{supplier.company_name} quoted R{amount:,.2f} for {booking.route}.",
                      type="info", ref_type="booking", ref_id=booking.ref)

    db.session.commit()
    log_action(current_user.id, "SUBMIT_QUOTE", "Booking", booking.ref,
               f"Amount R{amount:,.2f}")
    flash(f"Quote of R{amount:,.2f} submitted for {booking.ref}.", "success")
    return redirect(url_for("supplier.quote_requests"))


# ── Active Bookings ───────────────────────────────────────────────────────────

@supplier_bp.route("/bookings")
@supplier_required
def bookings():
    supplier = get_supplier()
    status   = request.args.get("status", "")
    query    = supplier.bookings.order_by(Booking.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    all_bookings = query.all()
    expired_any = False
    for b in all_bookings:
        if expire_supplier_response_if_needed(b):
            db.session.add(BookingStatusEvent(booking_id=b.id, status="Supplier SLA Expired",
                note="Supplier missed the 12-hour accept + driver assignment window.", actor="System"))
            expired_any = True
    if expired_any:
        db.session.commit()
    pending = [b for b in all_bookings if b.status == "Pending Supplier Acceptance"]
    drivers = supplier.drivers.filter_by(status="Active").all()
    return render_template("supplier/bookings.html",
        title="Bookings",
        supplier=supplier,
        bookings=[booking_to_v19(b) for b in all_bookings],
        pending=[booking_to_v19(b) for b in pending],
        drivers=[{"id": d.id, "name": d.name,
                  "vehicleType": f"License {d.license_code}" if d.license_code else "-",
                  "vehicleReg": d.phone or ""} for d in drivers],
        status_filter=status)


@supplier_bp.route("/bookings/<ref>/accept", methods=["POST"])
@supplier_required
def accept_booking(ref):
    supplier = get_supplier()
    booking  = Booking.query.filter_by(ref=ref, supplier_id=supplier.id).first_or_404()

    ok, reason = supplier_can_accept(booking)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("supplier.bookings"))

    booking.status       = "Pending Dispatch"
    booking.supplier_accepted_at = datetime.utcnow()
    booking.supplier_sla_status = "Accepted"

    event = BookingStatusEvent(booking_id=booking.id, status=booking.status,
        note=f"Booking accepted by {supplier.company_name}. Driver assignment is still required within the 12-hour SLA window.",
        actor=current_user.full_name)
    db.session.add(event)
    po = ensure_supplier_purchase_order(booking)
    log_finance_event(booking, "Supplier PO Created",
        f"{po.po_number} created instantly from the accepted quote. Supplier payout remains locked until delivery, POD, invoice upload, and admin verification.",
        current_user.full_name)
    db.session.commit()

    push_notification(booking.shipper.user_id,
        f"Booking confirmed - {booking.ref}",
        f"{supplier.company_name} has accepted your booking. They must assign a driver within the 12-hour SLA window before dispatch can proceed.",
        type="success", ref_type="booking", ref_id=booking.ref)

    flash(f"Booking {booking.ref} accepted. Purchase order {po.po_number} generated. Assign a driver and vehicle before the 12-hour SLA expires.", "success")
    return redirect(url_for("supplier.dispatch"))


@supplier_bp.route("/bookings/<ref>/reject", methods=["POST"])
@supplier_required
def reject_booking(ref):
    supplier = get_supplier()
    booking  = Booking.query.filter_by(ref=ref, supplier_id=supplier.id).first_or_404()

    if booking.status != "Pending Supplier Acceptance":
        flash("This booking is no longer awaiting your response.", "error")
        return redirect(url_for("supplier.bookings"))

    booking.status      = "Quotes Received"   # falls back so shipper can pick another supplier's quote
    booking.supplier_id = None
    booking.accepted_quote_id = None
    booking.supplier_response_deadline = None
    booking.supplier_accepted_at = None
    booking.driver_assigned_at = None
    booking.supplier_sla_status = "Not Started"

    event = BookingStatusEvent(booking_id=booking.id, status="Quotes Received",
        note=f"Booking rejected by {supplier.company_name} - returned to shipper for re-selection",
        actor=current_user.full_name)
    db.session.add(event)
    db.session.commit()

    push_notification(booking.shipper.user_id,
        f"Supplier unavailable - {booking.ref}",
        f"{supplier.company_name} was unable to take this booking. Please review other quotes.",
        type="warning", ref_type="booking", ref_id=booking.ref)

    flash(f"Booking {booking.ref} rejected. Shipper has been notified.", "info")
    return redirect(url_for("supplier.bookings"))


# ── Dispatch ──────────────────────────────────────────────────────────────────

@supplier_bp.route("/dispatch")
@supplier_required
def dispatch():
    supplier = get_supplier()
    pending  = supplier.bookings.filter(
        Booking.status.in_(["Confirmed", "Pending Dispatch"])).order_by(Booking.supplier_accepted_at.desc(), Booking.created_at.desc()).all()
    active_jobs = supplier.bookings.filter(
        Booking.status.in_(["Driver Assigned", "Collected", "In Transit", "Approaching Destination"])).order_by(Booking.driver_assigned_at.desc(), Booking.created_at.desc()).all()

    dispatch_jobs = []
    for booking in pending:
        job = booking_to_v19(booking)
        eligibility = eligible_dispatch_data(booking, supplier)
        job.update({
            "eligibleDrivers": eligibility["eligible_drivers"],
            "blockedDrivers": eligibility["blocked_drivers"],
            "eligibleVehicles": eligibility["eligible_vehicles"],
            "blockedVehicles": eligibility["blocked_vehicles"],
            "assignmentOptions": eligibility["assignment_options"],
            "eligibleDriverCount": len(eligibility["eligible_drivers"]),
            "eligibleVehicleCount": len(eligibility["eligible_vehicles"]),
        })
        dispatch_jobs.append(job)

    available_drivers = [item["driver"] for item in (eligible_dispatch_data(pending[0], supplier)["eligible_drivers"] if pending else [])]
    available_fleet = [item["vehicle"] for item in (eligible_dispatch_data(pending[0], supplier)["eligible_vehicles"] if pending else [])]

    return render_template("supplier/dispatch.html",
        title="Dispatch Centre",
        supplier=supplier,
        dispatch_jobs=dispatch_jobs,
        pending_jobs=dispatch_jobs,
        active_jobs=[booking_to_v19(b) for b in active_jobs],
        available_drivers=available_drivers, available_fleet=available_fleet,
        available_trailers=Trailer.query.filter_by(supplier_id=supplier.id, status="Available").all())


@supplier_bp.route("/dispatch/<ref>/assign", methods=["POST"])
@supplier_required
def dispatch_assign(ref):
    supplier = get_supplier()
    booking  = Booking.query.filter_by(ref=ref, supplier_id=supplier.id).first_or_404()
    assignment_pair = request.form.get("assignment_pair", "")
    driver_id  = request.form.get("driver_id")
    vehicle_id = request.form.get("vehicle_id")
    trailer_id = request.form.get("trailer_id")
    if assignment_pair and ":" in assignment_pair:
        driver_id, vehicle_id = assignment_pair.split(":", 1)

    ok, reason = can_dispatch(booking)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("supplier.dispatch"))
    if not driver_id or not vehicle_id:
        flash("Choose an eligible driver and vehicle pair before dispatch.", "error")
        return redirect(url_for("supplier.dispatch"))

    driver = Driver.query.filter_by(id=driver_id, supplier_id=supplier.id).first()
    vehicle = Vehicle.query.filter_by(id=vehicle_id, supplier_id=supplier.id).first()
    if not driver or not vehicle:
        flash("Selected driver or vehicle does not belong to your supplier account.", "error")
        return redirect(url_for("supplier.dispatch"))

    driver_ok, driver_reason = driver_is_available(driver)
    if not driver_ok:
        flash(f"Selected driver is not eligible: {driver_reason}", "error")
        return redirect(url_for("supplier.dispatch"))

    vehicle_ok, vehicle_reason = vehicle_is_available(vehicle)
    if not vehicle_ok:
        flash(f"Selected vehicle is not available: {vehicle_reason}", "error")
        return redirect(url_for("supplier.dispatch"))

    fit_ok, fit = vehicle_fits_booking(booking, vehicle)
    if not fit_ok:
        reason = "; ".join(fit.get("reasons") or ["Vehicle does not meet this shipment's load profile."])
        flash(f"Selected vehicle is not eligible for this job: {reason}", "error")
        return redirect(url_for("supplier.dispatch"))

    trailer = None
    if trailer_id:
        trailer = Trailer.query.filter_by(id=int(trailer_id), supplier_id=supplier.id).first()
        if not trailer or trailer.status != "Available":
            flash("Selected trailer is unavailable or does not belong to your account.", "error")
            return redirect(url_for("supplier.dispatch"))

    booking.driver_id = driver.id
    booking.driver_assigned_at = datetime.utcnow()
    booking.supplier_sla_status = "Completed"
    driver.status = "On Trip"
    booking.vehicle_id = vehicle.id
    vehicle.availability = "On Trip"
    if trailer:
        trailer.status = "On Trip"
    settings = ensure_settings(supplier)
    travel_hours = max(2.0, (booking.distance_km or 600) / 65.0)
    depart_at = datetime.combine(booking.collection_date or date.today(), datetime.min.time())
    eta_at = depart_at + timedelta(hours=travel_hours)
    available_at = eta_at + timedelta(minutes=settings.turnaround_buffer_minutes)
    existing_assignment = FleetAssignment.query.filter_by(booking_id=booking.id).first()
    assignment = existing_assignment or FleetAssignment(supplier_id=supplier.id, booking_id=booking.id)
    assignment.vehicle_id = vehicle.id; assignment.driver_id = driver.id
    assignment.trailer_id = trailer.id if trailer else None
    assignment.origin_city = booking.collection_city; assignment.destination_city = booking.delivery_city
    assignment.depart_at = depart_at; assignment.eta_at = eta_at; assignment.available_at = available_at
    assignment.projected_city = booking.delivery_city; assignment.return_load_status = "Required"
    assignment.dropoff_lat = booking.delivery_lat
    assignment.dropoff_lng = booking.delivery_lng
    if assignment.dropoff_lat is None or assignment.dropoff_lng is None:
        from app.services.capacity_planner import CITY_COORDS
        fallback = CITY_COORDS.get((booking.delivery_city or "").lower())
        if fallback: assignment.dropoff_lat, assignment.dropoff_lng = fallback
    assignment.next_booking_id = None
    db.session.add(assignment)
    ensure_delivery_pod_token(booking)

    booking.status = "Driver Assigned"
    booking.confirmed_at = booking.confirmed_at or booking.driver_assigned_at
    event = BookingStatusEvent(booking_id=booking.id, status="Driver Assigned",
                                note=f"Driver {driver.name} assigned to {vehicle.vehicle_type} ({vehicle.reg_number}) by {supplier.company_name}; supplier SLA completed.",
                                actor=current_user.full_name)
    db.session.add(event)

    push_notification(booking.shipper.user_id,
                      f"Driver assigned - {booking.ref}",
                      f"{driver.name} will collect on {booking.collection_date or 'the booked pickup date'} from {booking.collection_address or booking.collection_city}. Vehicle: {vehicle.vehicle_type} ({vehicle.reg_number}). Prepare goods and label/QR for collection.",
                      type="success", ref_type="booking", ref_id=booking.ref)

    db.session.commit()
    log_action(current_user.id, "DISPATCH", "Booking", ref)
    flash(f"{driver.name} assigned with {vehicle.reg_number}" + (f" + trailer {trailer.asset_number}" if trailer else "") + f" for {ref}.", "success")
    return redirect(url_for("supplier.dispatch"))


@supplier_bp.route("/bookings/<ref>/update-status", methods=["POST"])
@supplier_required
def update_status(ref):
    supplier  = get_supplier()
    booking   = Booking.query.filter_by(ref=ref, supplier_id=supplier.id).first()
    if not booking:
        # Some demo data has an accepted supplier quote before booking.supplier_id is synced.
        booking = Booking.query.join(Quote, Booking.id == Quote.booking_id)            .filter(Booking.ref == ref, Quote.supplier_id == supplier.id, Quote.status.in_(["Accepted", "Selected"]))            .first_or_404()
        booking.supplier_id = supplier.id
    new_status = request.form.get("status")
    note       = request.form.get("note", "")

    if not new_status:
        flash("Choose a booking status before submitting.", "error")
        return redirect(url_for("supplier.bookings"))

    # Suppliers can accept/reject bookings and dispatch resources, but they must
    # not fake live driver milestones from the supplier portal. Collection,
    # in-transit, approaching and delivery updates must come from the assigned
    # driver app/POD scan so tracking and audit history stay trustworthy.
    driver_only_statuses = {"Collected", "In Transit", "Approaching Destination", "Delivered"}
    if new_status in driver_only_statuses:
        flash("Driver trip milestones are locked to the assigned driver/POD scan workflow.", "error")
        return redirect(url_for("supplier.bookings"))

    if new_status == "Pending Dispatch" and booking.status == "Pending Supplier Acceptance":
        from app.services.lifecycle import supplier_can_accept
        ok, reason = supplier_can_accept(booking)
        if not ok:
            flash(reason, "error")
            return redirect(url_for("supplier.bookings"))
        booking.status = "Pending Dispatch"
        booking.supplier_id = supplier.id
        booking.supplier_accepted_at = datetime.utcnow()
        booking.supplier_sla_status = "Accepted"
    else:
        from app.services.lifecycle import can_transition
        ok, reason = can_transition(booking, new_status)
        if not ok:
            flash(reason, "error")
            return redirect(url_for("supplier.bookings"))
        booking.status = new_status
        if new_status == "Cancelled":
            if booking.driver:
                booking.driver.status = "Active"
            if booking.vehicle:
                booking.vehicle.availability = "Available"

    event = BookingStatusEvent(booking_id=booking.id, status=booking.status,
                                note=note or f"Supplier updated booking to {booking.status}",
                                actor=current_user.full_name)
    db.session.add(event)

    push_notification(booking.shipper.user_id,
                      f"Shipment update - {booking.ref}",
                      f"Status changed to: {booking.status}.",
                      type="info", ref_type="booking", ref_id=booking.ref)

    db.session.commit()
    flash(f"Status updated to {booking.status}.", "success")
    return redirect(url_for("supplier.bookings"))


# ── Fleet ─────────────────────────────────────────────────────────────────────

@supplier_bp.route("/fleet")
@supplier_required
def fleet():
    supplier = get_supplier()
    vehicles = supplier.vehicles.all()
    fleet = [{
        "id": v.id,
        "type": v.vehicle_type or "-",
        "reg": v.reg_number or "-",
        "payload": f"{v.payload_ton:g}T" if v.payload_ton is not None else "-",
        "cbm": f"{v.cbm:g} CBM" if v.cbm is not None else "-",
        "availability": v.availability or "Available",
        "docs_status": "Verified" if v.roadworthy_expiry else "Pending",
    } for v in vehicles]
    return render_template("supplier/fleet.html", title="Fleet", supplier=supplier, vehicles=vehicles, fleet=fleet)


@supplier_bp.route("/fleet/add", methods=["POST"])
@supplier_required
def add_vehicle():
    supplier = get_supplier()
    reg      = (request.form.get("reg_number") or request.form.get("reg") or "").strip().upper()
    if not reg:
        flash("Registration number is required.", "error")
        return redirect(url_for("supplier.fleet"))
    if Vehicle.query.filter_by(reg_number=reg).first():
        flash(f"Vehicle {reg} already exists.", "error")
        return redirect(url_for("supplier.fleet"))

    def _num(value):
        import re
        cleaned = re.sub(r"[^0-9.]", "", str(value or ""))
        return float(cleaned) if cleaned else 0.0

    v = Vehicle(
        supplier_id  = supplier.id,
        reg_number   = reg,
        vehicle_type = request.form.get("vehicle_type") or request.form.get("type") or "",
        payload_ton  = _num(request.form.get("payload_ton") or request.form.get("payload")),
        cbm          = _num(request.form.get("cbm") or request.form.get("cubicCapacity")),
        year         = int(request.form.get("year", 2020) or 2020),
    )
    rw = request.form.get("roadworthy_expiry","")
    if rw:
        v.roadworthy_expiry = date.fromisoformat(rw)
    db.session.add(v)
    db.session.commit()
    flash(f"Vehicle {reg} added.", "success")
    return redirect(url_for("supplier.fleet"))


@supplier_bp.route("/fleet/<int:vid>/delete", methods=["POST"])
@supplier_required
def delete_vehicle(vid):
    supplier = get_supplier()
    v = Vehicle.query.filter_by(id=vid, supplier_id=supplier.id).first_or_404()
    db.session.delete(v)
    db.session.commit()
    flash("Vehicle removed.", "info")
    return redirect(url_for("supplier.fleet"))


# ── Drivers ───────────────────────────────────────────────────────────────────

@supplier_bp.route("/drivers")
@supplier_required
def drivers():
    supplier = get_supplier()
    driver_rows = []
    for d in supplier.drivers.order_by(Driver.name).all():
        active = d.bookings.filter(Booking.status.in_(["Driver Assigned", "Collected", "In Transit", "Approaching Destination"])).first()
        display_vehicle = active.vehicle if active and active.vehicle else None
        driver_rows.append({
            "id": d.id,
            "name": d.name,
            "phone": d.phone or "-",
            "licenseType": d.license_code or "EC",
            "licenseExpiry": d.license_expiry.strftime("%Y-%m-%d") if d.license_expiry else "-",
            "assignedVehicleId": None,
            "vehicleType": display_vehicle.vehicle_type if display_vehicle else "Assigned per job",
            "vehicleReg": display_vehicle.reg_number if display_vehicle else "-",
            "homeVehicleType": "Assigned per job",
            "homeVehicleReg": "-",
            "status": d.status or "Active",
            "vettingStatus": d.vetting_status or "Pending",
        })
    fleet_rows = [{"id": v.id, "type": v.vehicle_type or "Vehicle", "reg": v.reg_number, "driverId": None} for v in supplier.vehicles.order_by(Vehicle.reg_number).all()]
    return render_template("supplier/drivers.html",
        title="Drivers", supplier=supplier, drivers=driver_rows, fleet=fleet_rows)


@supplier_bp.route("/drivers/add", methods=["POST"])
@supplier_required
def add_driver():
    supplier = get_supplier()
    d = Driver(
        supplier_id  = supplier.id,
        name         = request.form.get("name","").strip(),
        id_number    = request.form.get("id_number","").strip(),
        license_code = request.form.get("license_code","EC"),
        phone        = request.form.get("phone","").strip(),
    )
    exp = request.form.get("license_expiry","")
    if exp:
        d.license_expiry = date.fromisoformat(exp)
    # Vetting fields
    ccd = request.form.get("criminal_clearance_date","")
    if ccd:
        d.criminal_clearance_date = date.fromisoformat(ccd)
    d.criminal_clearance_status = request.form.get("criminal_clearance_status","Pending")
    pdp = request.form.get("pdp_expiry","")
    if pdp:
        d.pdp_expiry = date.fromisoformat(pdp)
    d.vetting_status = request.form.get("vetting_status","Pending")
    # Drivers are not permanently tied to vehicles. Vehicle selection happens per job on Dispatch.
    d.assigned_vehicle_id = None
    db.session.add(d)
    db.session.commit()
    flash(f"Driver {d.name} added. Assign a vehicle per job from Dispatch.", "success")
    return redirect(url_for("supplier.drivers"))


@supplier_bp.route("/drivers/<int:driver_id>/assign-vehicle", methods=["POST"])
@supplier_required
def assign_driver_vehicle(driver_id):
    supplier = get_supplier()
    driver = Driver.query.filter_by(id=driver_id, supplier_id=supplier.id).first_or_404()
    driver.assigned_vehicle_id = None
    db.session.commit()
    flash(f"{driver.name} is available for job-based dispatch. Choose the vehicle on each booking.", "info")
    return redirect(url_for("supplier.drivers"))


# ── Availability ──────────────────────────────────────────────────────────────

@supplier_bp.route("/availability")
@supplier_required
def availability():
    supplier = get_supplier()
    blocks   = supplier.availability.filter_by(is_blocked=True).order_by(AvailabilitySlot.date).all()
    blocked_dates = [
        {"id": b.id, "date": b.date.isoformat(), "type": b.block_type or "maintenance",
         "reason": b.reason or "Unavailable"}
        for b in blocks
    ]
    return render_template("supplier/availability.html",
        title="Availability", supplier=supplier,
        blocked_dates=blocked_dates,
        today=date.today().isoformat())


@supplier_bp.route("/availability/block", methods=["POST"])
@supplier_required
def block_availability():
    supplier = get_supplier()
    try:
        block_date = date.fromisoformat(request.form.get("date", ""))
    except ValueError:
        flash("Please select a valid date.", "error")
        return redirect(url_for("supplier.availability"))

    block = AvailabilitySlot(
        supplier_id = supplier.id,
        date        = block_date,
        is_blocked  = True,
        block_type  = request.form.get("type", "maintenance"),
        reason      = request.form.get("reason", "").strip() or "Unavailable",
    )
    db.session.add(block)
    db.session.commit()
    flash(f"{block_date.strftime('%d %b %Y')} blocked - you won't receive booking offers for that date.", "success")
    return redirect(url_for("supplier.availability"))


@supplier_bp.route("/availability/<int:block_id>/remove", methods=["POST"])
@supplier_required
def remove_availability_block(block_id):
    supplier = get_supplier()
    block = AvailabilitySlot.query.filter_by(
        id=block_id, supplier_id=supplier.id, is_blocked=True).first_or_404()
    db.session.delete(block)
    db.session.commit()
    flash("Block removed - that date is now open for booking offers again.", "info")
    return redirect(url_for("supplier.availability"))


@supplier_bp.route("/availability/add", methods=["POST"])
@supplier_required
def add_availability():
    supplier = get_supplier()
    slot = AvailabilitySlot(
        supplier_id  = supplier.id,
        date         = date.fromisoformat(request.form.get("date")),
        vehicle_type = request.form.get("vehicle_type",""),
        slots_total  = int(request.form.get("slots", 1)),
        note         = request.form.get("note",""),
    )
    db.session.add(slot)
    db.session.commit()
    flash("Availability slot added.", "success")
    return redirect(url_for("supplier.availability"))


# ── Performance ───────────────────────────────────────────────────────────────

@supplier_bp.route("/performance")
@supplier_required
def performance():
    supplier   = get_supplier()
    score_hist = supplier.score_history.order_by(
                    SupplierScoreHistory.recorded_at).all()
    platform_settings = {
        "delayUnder1hDeduction":    0.05,
        "delay1to3hDeduction":      0.10,
        "delayOver3hDeduction":     0.20,
        "dcSlotMissedDeduction":    0.25,
        "bookingRejectedDeduction": 0.15,
        "bookingTimedOutDeduction": 0.10,
        "cargoDamageDeduction":     0.50,
        "fiveStarBonus":            0.10,
        "oneStarDeduction":         0.20,
        "newSupplierStartScore":    4.0,
        "rollingWindowBookings":    50,
    }
    return render_template("supplier/performance.html",
        title="Performance", supplier=supplier,
        score_hist=score_hist, min_score=3.0, settings=platform_settings)


# ── Complaints ─────────────────────────────────────────────────────────────────

from app.models import Complaint  # local import

@supplier_bp.route("/complaints")
@supplier_required
def complaints():
    supplier = get_supplier()
    # Only show complaints that admin has forwarded to this supplier
    forwarded = supplier.complaints.filter(
        Complaint.status.in_(["Forwarded to Supplier", "Supplier Responded", "Resolved", "Closed"])
    ).order_by(Complaint.created_at.desc()).all()
    return render_template("supplier/complaints.html",
        title="Complaints", complaints=forwarded)


@supplier_bp.route("/complaints/<ref>", methods=["GET", "POST"])
@supplier_required
def complaint_detail(ref):
    supplier = get_supplier()
    c = Complaint.query.filter_by(ref=ref, supplier_id=supplier.id).first_or_404()

    # Supplier may only view/respond if forwarded
    if c.status not in ("Forwarded to Supplier", "Supplier Responded", "Resolved", "Closed"):
        flash("This complaint is not yet available for your review.", "warning")
        return redirect(url_for("supplier.complaints"))

    if request.method == "POST":
        response_text = request.form.get("supplier_response", "").strip()
        if response_text:
            c.supplier_response    = response_text
            c.supplier_responded_at = datetime.utcnow()
            c.status               = "Supplier Responded"
            db.session.commit()

            # Notify admins
            admins = User.query.filter_by(role="admin").all()
            for adm in admins:
                push_notification(adm.id,
                    f"Supplier responded - {c.ref}",
                    f"{supplier.company_name} has submitted their response to complaint {c.ref}.",
                    type="info", ref_type="complaint", ref_id=c.ref)

            flash("Your response has been submitted. Admin will review and resolve the complaint.", "success")
            return redirect(url_for("supplier.complaint_detail", ref=ref))
        else:
            flash("Please enter a response before submitting.", "error")

    return render_template("supplier/complaint_detail.html",
        title=f"Complaint {ref}", complaint=c)


# ═══════════════════════════════════════════════════════════════════════════
# BANKING & EARNINGS
# ═══════════════════════════════════════════════════════════════════════════

@supplier_bp.route("/banking", methods=["GET", "POST"])
@supplier_required
def banking():
    supplier = get_supplier()

    if request.method == "POST":
        supplier.account_holder = request.form.get("account_holder", "").strip()
        supplier.bank_name      = request.form.get("bank_name", "").strip()
        supplier.bank_branch    = request.form.get("branch_code", "").strip()
        supplier.account_type   = request.form.get("account_type", "Current / Cheque")
        supplier.bank_account   = request.form.get("account_number", "").strip()
        db.session.commit()
        flash("Banking details saved.", "success")
        return redirect(url_for("supplier.banking"))

    delivered = supplier.bookings.filter_by(status="Delivered").all()
    total_gross = sum((b.quoted_value or 0) for b in delivered)
    total_commission = sum((b.platform_fee or 0) for b in delivered)
    from app.models import Payout
    total_paid = sum(p.amount for p in supplier.payouts.all())
    total_pending = sum((b.supplier_payout or 0) for b in delivered) - total_paid
    return render_template("supplier/banking.html",
        title="Banking & earnings", supplier=supplier,
        total_gross=total_gross, total_commission=total_commission,
        total_paid=max(total_paid, 0), total_pending=max(total_pending, 0))


# ═══════════════════════════════════════════════════════════════════════════
# COMPLIANCE DOCUMENTS
# ═══════════════════════════════════════════════════════════════════════════

@supplier_bp.route("/documents")
@supplier_required
def documents():
    supplier = get_supplier()
    docs = supplier.documents.order_by(ComplianceDocument.uploaded_at.desc()).all()
    pending_requests = supplier.doc_requests.filter(
        DocumentRequest.status.in_(["Pending", "Overdue"])).all()
    return render_template("supplier/documents.html",
        title="Compliance documents", documents=docs, requests=pending_requests)


@supplier_bp.route("/documents/<int:doc_id>/download")
@supplier_required
def download_document(doc_id):
    supplier = get_supplier()
    doc = ComplianceDocument.query.get_or_404(doc_id)
    if doc.supplier_id != supplier.id:
        flash("Access denied.", "error")
        return redirect(url_for("supplier.documents"))
    filename = doc.filename
    if filename:
        path = os.path.abspath(os.path.join("app", "static", "supplier_documents", filename))
        if os.path.exists(path):
            return send_file(path, as_attachment=False, download_name=filename)
    content = f"FreightFlow Nexus supplier document\nDocument: {doc.name}\nStatus: {doc.status}\nFilename: {filename or 'Not uploaded'}\n"
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/plain", as_attachment=False, download_name=f"supplier-document-{doc.id}.txt")

@supplier_bp.route("/documents/upload", methods=["POST"])
@supplier_required
def upload_document():
    supplier = get_supplier()
    name = request.form.get("name", "").strip()
    f = request.files.get("file")

    if not name:
        flash("Please specify the document type.", "error")
        return redirect(url_for("supplier.documents"))

    filename = None

    if f and f.filename:
        import os, werkzeug.utils
        upload_dir = os.path.join("app", "static", "supplier_documents")
        os.makedirs(upload_dir, exist_ok=True)
        filename = werkzeug.utils.secure_filename(f"{supplier.id}_{name}_{f.filename}")
        f.save(os.path.join(upload_dir, filename))

    # Replace existing doc of same name if present (re-upload), else create new
    existing = supplier.documents.filter_by(name=name).first()
    if existing:
        existing.status = "Pending review"
        existing.filename = filename or existing.filename
        existing.uploaded_at = datetime.utcnow()
        existing.rejection_reason = None
    else:
        db.session.add(ComplianceDocument(
            supplier_id=supplier.id, name=name, status="Pending review",
            filename=filename))

    # Fulfil any matching document request
    matching_req = supplier.doc_requests.filter_by(doc_type=name, status="Pending").first()
    if matching_req:
        matching_req.status = "Fulfilled"
        matching_req.fulfilled_at = datetime.utcnow()

    db.session.commit()
    flash(f"{name} uploaded and submitted for review.", "success")
    return redirect(url_for("supplier.documents"))


# ═══════════════════════════════════════════════════════════════════════════
# RATE CARDS
# ═══════════════════════════════════════════════════════════════════════════

@supplier_bp.route("/rates")
@supplier_required
def rates():
    supplier = get_supplier()
    cards = supplier.rate_cards.order_by(RateCard.route).all()
    return render_template("supplier/rates.html", title="Rate cards", rate_cards=cards)


@supplier_bp.route("/rates/add", methods=["POST"])
@supplier_required
def add_rate_card():
    supplier = get_supplier()
    route = request.form.get("route", "").strip()
    existing = supplier.rate_cards.filter_by(route=route).first()
    new_version = f"v{int(existing.version[1:])+1}" if existing and existing.version[1:].isdigit() else "v1"
    if existing:
        existing.is_active = False  # supersede old version

    card = RateCard(
        supplier_id=supplier.id, route=route,
        vehicle_type=request.form.get("vehicle_type", "").strip(),
        load_type=request.form.get("load_type", "").strip(),
        base_rate=request.form.get("base_rate", type=float) or 0,
        fuel_surcharge_pct=request.form.get("fuel_surcharge_pct", type=float) or 0,
        minimum_charge=request.form.get("minimum_charge", type=float) or 0,
        version=new_version,
    )
    db.session.add(card)
    db.session.commit()
    flash(f"Rate card for {route} saved ({new_version}).", "success")
    return redirect(url_for("supplier.rates"))


# ═══════════════════════════════════════════════════════════════════════════
# DRIVER LOGINS (PIN management)
# ═══════════════════════════════════════════════════════════════════════════

@supplier_bp.route("/driver-logins")
@supplier_required
def driver_logins():
    supplier = get_supplier()
    drivers = supplier.drivers.order_by(Driver.name).all()
    return render_template("supplier/driver_logins.html", title="Driver logins", drivers=drivers)


@supplier_bp.route("/drivers/<int:driver_id>/reset-pin", methods=["POST"])
@supplier_required
def reset_driver_pin(driver_id):
    supplier = get_supplier()
    driver = Driver.query.filter_by(id=driver_id, supplier_id=supplier.id).first_or_404()
    import random
    driver.pin = f"{random.randint(1000,9999)}"
    db.session.commit()
    flash(f"New PIN for {driver.name}: {driver.pin}", "success")
    return redirect(url_for("supplier.driver_logins"))


# ═══════════════════════════════════════════════════════════════════════════
# PURCHASE ORDERS (invoice upload workflow)
# ═══════════════════════════════════════════════════════════════════════════

@supplier_bp.route("/purchase-orders")
@supplier_required
def purchase_orders():
    supplier = get_supplier()
    pos = PurchaseOrder.query.join(Booking).filter(Booking.supplier_id == supplier.id)\
        .order_by(PurchaseOrder.created_at.desc()).all()
    return render_template("supplier/purchase_orders.html", title="Purchase orders", purchase_orders=pos)


@supplier_bp.route("/purchase-orders/<int:po_id>")
@supplier_required
def purchase_order_detail(po_id):
    supplier = get_supplier()
    po = PurchaseOrder.query.get_or_404(po_id)
    if po.booking.supplier_id != supplier.id:
        flash("Access denied.", "error")
        return redirect(url_for("supplier.purchase_orders"))
    return render_template("supplier/po_detail.html", title=po.po_number, po=po)


@supplier_bp.route("/purchase-orders/<int:po_id>/upload-invoice", methods=["POST"])
@supplier_required
def upload_po_invoice(po_id):
    supplier = get_supplier()
    po = PurchaseOrder.query.get_or_404(po_id)
    if po.booking.supplier_id != supplier.id:
        flash("Access denied.", "error")
        return redirect(url_for("supplier.purchase_orders"))

    f = request.files.get("invoice")
    if not po.booking.delivery_evidence:
        flash("Invoice submission is locked until the driver captures complete POD evidence, signatures and GPS.", "error")
        return redirect(url_for("supplier.purchase_order_detail", po_id=po_id))
    ok, reason = can_supplier_upload_invoice(po.booking)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("supplier.purchase_order_detail", po_id=po_id))

    if po.status == "Paid":
        flash("This PO has already been paid and cannot be changed.", "error")
        return redirect(url_for("supplier.purchase_order_detail", po_id=po_id))

    if f and f.filename:
        import os, werkzeug.utils
        upload_dir = os.path.join("app", "static", "supplier_invoices")
        os.makedirs(upload_dir, exist_ok=True)
        filename = werkzeug.utils.secure_filename(f"{po.po_number}_{f.filename}")
        f.save(os.path.join(upload_dir, filename))
        po.invoice_filename = filename
        po.invoice_uploaded_at = datetime.utcnow()
        po.status = "Invoice Received"
        log_finance_event(po.booking, "Invoice Package Submitted",
            f"Supplier submitted invoice {filename} with the complete supporting evidence package for {po.po_number}. Admin finance review is required before payout.",
            current_user.full_name)
        notify_all_role(
            "admin",
            f"Invoice package ready for review - {po.po_number}",
            f"{supplier.company_name} submitted an invoice and complete supporting evidence for booking {po.booking.ref}. Review the invoice, PO, waybill, POD, signatures, GPS and delivery documents before approving payment.",
            type="warning",
        )
        db.session.commit()
        flash("Invoice package sent to admin for review. Payment will remain locked until admin approval.", "success")
    else:
        flash("Please select a file to upload.", "error")
    return redirect(url_for("supplier.purchase_order_detail", po_id=po_id))


@supplier_bp.route("/purchase-orders/<int:po_id>/invoice/download")
@supplier_required
def download_po_invoice(po_id):
    supplier = get_supplier()
    po = PurchaseOrder.query.get_or_404(po_id)
    if po.booking.supplier_id != supplier.id:
        flash("Access denied.", "error")
        return redirect(url_for("supplier.purchase_orders"))
    filename = po.invoice_filename
    if filename:
        path = os.path.abspath(os.path.join("app", "static", "supplier_invoices", filename))
        if os.path.exists(path):
            return send_file(path, as_attachment=False, download_name=filename)
    content = f"FreightFlow Nexus PO invoice record\nPO: {po.po_number}\nStatus: {po.status}\nInvoice file: {filename or 'No invoice uploaded'}\nNet payable: R{(po.net_payable or 0):,.2f}\n"
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/plain", as_attachment=False, download_name=f"{po.po_number}-invoice-record.txt")

# ═══════════════════════════════════════════════════════════════════════════
# SUPPLIER ↔ DRIVER CHAT
# ═══════════════════════════════════════════════════════════════════════════

@supplier_bp.route("/chat")
@supplier_required
def chat_inbox():
    supplier = get_supplier()
    drivers = supplier.drivers.order_by(Driver.name).all()
    last_messages = {}
    for d in drivers:
        last = d.chat_messages.order_by(ChatMessage.created_at.desc()).first()
        last_messages[d.id] = last
    return render_template("supplier/chat.html", title="Driver chat",
        drivers=drivers, last_messages=last_messages)


@supplier_bp.route("/chat/<int:driver_id>")
@supplier_required
def chat_thread(driver_id):
    supplier = get_supplier()
    driver = Driver.query.filter_by(id=driver_id, supplier_id=supplier.id).first_or_404()
    messages = driver.chat_messages.order_by(ChatMessage.created_at).all()
    # Mark driver->supplier messages as read
    driver.chat_messages.filter_by(sender_role="driver", is_read=False).update({"is_read": True})
    db.session.commit()
    drivers = supplier.drivers.order_by(Driver.name).all()
    return render_template("supplier/chat.html", title=f"Chat - {driver.name}",
        drivers=drivers, active_driver=driver, messages=messages, last_messages={})


@supplier_bp.route("/chat/<int:driver_id>/send", methods=["POST"])
@supplier_required
def chat_send(driver_id):
    supplier = get_supplier()
    driver = Driver.query.filter_by(id=driver_id, supplier_id=supplier.id).first_or_404()
    text = request.form.get("text", "").strip()
    if text:
        db.session.add(ChatMessage(supplier_id=supplier.id, driver_id=driver.id,
                                    sender_role="supplier", text=text))
        db.session.commit()
    return redirect(url_for("supplier.chat_thread", driver_id=driver_id))


@supplier_bp.route("/profile", methods=["GET", "POST"])
@supplier_required
def profile():
    supplier = get_supplier()
    if request.method == "POST":
        supplier.company_name = request.form.get("companyName", supplier.company_name).strip() or supplier.company_name
        supplier.operating_region = request.form.get("operatingRegions", supplier.operating_region).strip() or supplier.operating_region
        supplier.base_city = request.form.get("baseOfOperations", supplier.base_city).strip() or supplier.base_city
        if request.form.get("phone"):
            current_user.phone = request.form.get("phone").strip()
        db.session.commit()
        flash("Supplier profile saved.", "success")
        return redirect(url_for("supplier.profile"))
    cities = ["Johannesburg", "Cape Town", "Durban", "Pretoria", "Gqeberha", "Bloemfontein", "Polokwane", "Mbombela", "Rustenburg", "Kimberley", "East London", "Pietermaritzburg", "Krugersdorp", "Vereeniging", "Richards Bay"]
    return render_template("supplier/profile.html", title="Company profile", supplier=supplier, cities=cities)


# ═══════════════════════════════════════════════════════════════════════════
# CONTAINER QUOTES
# ═══════════════════════════════════════════════════════════════════════════

@supplier_bp.route("/container-quotes")
@supplier_required
def container_quotes():
    supplier = get_supplier()
    # Container quotes stored as RateCard objects - using route + load_type fields
    from app.models import RateCard
    quotes = RateCard.query.filter_by(supplier_id=supplier.id).order_by(RateCard.created_at.desc()).all()
    # Map to template-friendly dicts
    quote_dicts = []
    for q in quotes:
        rate = q.base_rate or 0
        platform_fee = round(rate * 0.10, 2)
        route_parts  = (q.route or "-").split(" -> ") if " -> " in (q.route or "") else [(q.route or "-"), ""]
        origin      = route_parts[0]
        destination = route_parts[1] if len(route_parts) > 1 else ""
        quote_dicts.append({
            "id":            q.id,
            "route":         q.route or "-",
            "origin":        origin,
            "destination":   destination,
            "containerType": q.vehicle_type or "20ft",
            "ratePerContainer": rate,
            "platformFeePct": 10,
            "yourRate":      rate,
            "platformFee":   platform_fee,
            "shipperPrice":  round(rate + platform_fee, 2),
            "validFrom":     q.created_at.strftime("%d %b %Y") if q.created_at else "-",
            "validTo":       "-",
            "status":        "Active" if q.is_active else "Inactive",
        })
    return render_template("supplier/container_quotes.html",
        title="Container quotes", supplier=supplier, quotes=quote_dicts)


@supplier_bp.route("/container-quotes/add", methods=["POST"])
@supplier_required
def add_container_quote():
    from app.models import RateCard
    supplier = get_supplier()
    origin      = request.form.get("origin", "").strip()
    destination = request.form.get("destination", "").strip()
    container   = request.form.get("container_type", "20ft")
    rate        = float(request.form.get("ratePerContainer") or request.form.get("rate") or 0)
    valid_from_s = request.form.get("valid_from", "")
    valid_to_s   = request.form.get("valid_to", "")

    from datetime import date as ddate
    vf = ddate.fromisoformat(valid_from_s) if valid_from_s else ddate.today()
    vt = ddate.fromisoformat(valid_to_s) if valid_to_s else None

    rc = RateCard(supplier_id=supplier.id,
                  route=f"{origin} -> {destination}",
                  vehicle_type=container, base_rate=rate,
                  load_type="Container", is_active=False)  # False = pending admin approval
    db.session.add(rc)
    db.session.commit()
    flash(f"Container quote submitted for {origin} -> {destination}. Pending admin approval.", "success")
    return redirect(url_for("supplier.container_quotes"))


@supplier_bp.route("/container-quotes/<int:qid>/delete", methods=["POST"])
@supplier_required
def delete_container_quote(qid):
    from app.models import RateCard
    supplier = get_supplier()
    rc = RateCard.query.filter_by(id=qid, supplier_id=supplier.id).first_or_404()
    db.session.delete(rc)
    db.session.commit()
    flash("Container quote removed.", "info")
    return redirect(url_for("supplier.container_quotes"))


# ── Missing routes referenced from sidebar nav ─────────────────────────────

@supplier_bp.route("/compliance")
@supplier_required
def compliance():
    supplier = get_supplier()
    docs = supplier.documents.order_by(db.text('uploaded_at DESC')).all()
    for doc in docs:
        # Template compatibility aliases used by the compliance dashboard.
        doc.days_left = doc.days_to_expiry
        doc.expiry = doc.expiry_date
    return render_template("supplier/compliance.html",
        title="Compliance", supplier=supplier, documents=docs)

@supplier_bp.route("/insights")
@supplier_required  
def insights():
    supplier = get_supplier()
    my_bookings  = supplier.bookings.order_by(Booking.created_at.desc()).all()
    delivered    = [b for b in my_bookings if b.status in ("Delivered", "Completed")]
    active       = [b for b in my_bookings if b.status in ("Confirmed", "Driver Assigned", "Collected", "In Transit", "Approaching Destination")]

    total_jobs    = len(delivered)
    total_revenue = sum(b.supplier_payout or 0 for b in delivered)
    on_time       = sum(1 for b in delivered if b.delivered_at and b.collection_date
                        and b.delivered_at.date() <= b.collection_date + timedelta(days=1))
    on_time_pct   = round(on_time / total_jobs * 100, 1) if total_jobs else 0
    on_time_rate  = on_time_pct

    rated = [b for b in delivered if b.rating]
    avg_rating = round(sum(b.rating for b in rated) / len(rated), 1) if rated else 0.0

    total_earned  = sum(b.supplier_payout or 0 for b in delivered)
    paid_bookings = [b for b in delivered if b.invoice and b.invoice.status == "Paid"]
    total_paid    = sum(b.supplier_payout or 0 for b in paid_bookings)
    outstanding   = round(total_earned - total_paid, 2)

    accepted   = sum(1 for b in my_bookings if b.status not in ("Cancelled", "Supplier Rejected", "Supplier SLA Expired"))
    total_req  = len(my_bookings)
    accept_rate = round(accepted / total_req * 100, 1) if total_req else 100.0
    vehicles_on_trip = supplier.vehicles.filter_by(availability="On Trip").count()
    total_veh   = supplier.vehicles.count()
    fleet_util  = round(vehicles_on_trip / total_veh * 100, 1) if total_veh else 0
    avg_booking_value = round(total_earned / total_jobs, 2) if total_jobs else 0
    stats = {
        "acceptanceRate":  accept_rate,
        "fleetUtilPct":    fleet_util,
        "avgInvoiceDays":  2,
        "avgBookingValue": avg_booking_value,
    }

    bench = {
        "avgOnTimePct":      82.0,
        "avgAcceptanceRate": 78.0,
        "avgScore":          4.1,
        "avgInvoiceDays":    3,
        "avgFleetUtil":      55.0,
        "avgBookingValue":   18000,
    }

    # Last 6 calendar months for charts. Always pass a list so Chart.js never hits Undefined.
    month_rows = []
    today = date.today().replace(day=1)
    for i in range(5, -1, -1):
        # month arithmetic without external dependencies
        month = today.month - i
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        label_date = date(year, month, 1)
        rows = [b for b in my_bookings if b.created_at and b.created_at.year == year and b.created_at.month == month]
        month_rows.append({
            "month": label_date.strftime("%b"),
            "bookings": len(rows),
            "revenue": round(sum(b.supplier_payout or b.quoted_value or 0 for b in rows), 2),
        })

    score_hist = supplier.score_history.order_by(SupplierScoreHistory.recorded_at.desc()).limit(12).all()
    score_hist_v19 = [{
        "event": f"Score snapshot: {h.score:.1f}/5",
        "date": h.recorded_at.strftime("%d %b") if h.recorded_at else "-",
        "impact": 0,
        "score": h.score,
    } for h in score_hist]
    trajectory = [round(h.score, 2) for h in reversed(score_hist[-6:])] if score_hist else [supplier.score or 4.0] * 6

    my_quotes = []
    for q in supplier.quotes.order_by(Quote.created_at.desc()).limit(10).all():
        b = q.booking
        my_quotes.append({
            "origin": b.collection_city if b else "-",
            "destination": b.delivery_city if b else "-",
            "containerType": (b.vehicle_type_req if b else "General freight") or "General freight",
            "ratePerContainer": q.amount or 0,
            "status": "Active" if q.status in ("Accepted", "Selected") else q.status or "Pending approval",
        })

    my_drivers = [driver_to_v19(d) for d in supplier.drivers.order_by(Driver.name).all()]

    return render_template("supplier/insights.html",
        title="Performance Insights", supplier=supplier,
        my_bookings=my_bookings, delivered=delivered, active=active,
        total_jobs=total_jobs, total_revenue=total_revenue,
        on_time_pct=on_time_pct, on_time_rate=on_time_rate,
        avg_rating=avg_rating,
        total_earned=total_earned, total_paid=total_paid, outstanding=outstanding,
        stats=stats, bench=bench, trajectory=trajectory,
        monthly=month_rows, score_hist=score_hist_v19, my_quotes=my_quotes,
        my_drivers=my_drivers)

@supplier_bp.route("/invoices")
@supplier_required
def invoices():
    supplier = get_supplier()
    settings = PlatformSettings.query.first()
    platform_fee_pct = settings.platform_fee_pct if settings else 26.7
    completed = supplier.bookings.filter(Booking.status.in_(["Delivered", "Completed"])).order_by(Booking.created_at.desc()).all()
    completed_bookings = []
    for b in completed:
        row = booking_to_v19(b)
        po = b.purchase_order
        inv = b.invoice
        row["payout_status"] = (po.status if po else ("Paid" if inv and inv.status == "Paid" else "Pending"))
        row["value"] = row.get("value") or b.quoted_value or b.supplier_payout or 0
        completed_bookings.append(row)
    return render_template("supplier/invoices.html",
        title="Invoices", supplier=supplier,
        completed_bookings=completed_bookings,
        platform_fee_pct=platform_fee_pct)

@supplier_bp.route("/reports")
@supplier_required
def reports():
    supplier = get_supplier()
    from app.models import Complaint
    complaints = supplier.complaints.order_by(Complaint.created_at.desc()).all()
    # Template uses 'notifications' and 'unread' (complaint-notification hybrid template)
    notifications = [{
        "id":         c.ref,
        "status":     "Unread" if c.status == "Open" else "Responded" if c.status == "In Progress" else "Read",
        "category":   c.category or "Complaint",
        "bookingRef": c.booking_ref or "-",
        "message":    c.body or "",
        "sentAt":     c.created_at.strftime("%d %b %Y") if c.created_at else "-",
        "sentBy":     "Shipper",
    } for c in complaints]
    unread = sum(1 for n in notifications if n["status"] == "Unread")
    return render_template("supplier/reports.html",
        title="Reports & Complaints", supplier=supplier,
        complaints=complaints, notifications=notifications, unread=unread)

@supplier_bp.route("/tracking")
@supplier_required
def tracking():
    supplier = get_supplier()
    active_bookings = supplier.bookings.filter(
        Booking.status.in_(["Driver Assigned", "Collected", "In Transit", "Approaching Destination"])).all()
    active_by_driver = {b.driver_id: booking_to_v19(b) for b in active_bookings if b.driver_id}
    drivers = []
    for d in supplier.drivers.order_by(Driver.name).all():
        dv = driver_to_v19(d)
        dv["active_booking"] = active_by_driver.get(d.id)
        drivers.append(dv)
    return render_template("supplier/tracking.html",
        title="Live tracking", supplier=supplier,
        bookings=[booking_to_v19(b) for b in active_bookings],
        drivers=drivers,
        active_count=sum(1 for d in drivers if d.get("active_booking")),
        google_maps_key=current_app.config.get("GOOGLE_MAPS_KEY") or current_app.config.get("GOOGLE_MAPS_API_KEY", ""))

# ── Supplier document hub / operational evidence pack ────────────────────────
def _supplier_pod_files(booking):
    from app.services.evidence_pack import pod_files
    return pod_files(booking)


def _booking_po(booking):
    return PurchaseOrder.query.filter_by(booking_id=booking.id).order_by(PurchaseOrder.created_at.desc()).first()


@supplier_bp.route('/booking/<ref>/documents')
@supplier_required
def booking_documents(ref):
    supplier = get_supplier()
    booking = Booking.query.filter_by(ref=ref, supplier_id=supplier.id).first_or_404()
    po = _booking_po(booking)
    pod_files = _supplier_pod_files(booking)
    waybill_ok, waybill_reason = can_view_waybill(booking)
    from app.services.evidence_pack import pod_meta
    return render_template('supplier/documents.html', title=f'Documents - {ref}',
        booking=booking, po=po, pod_files=pod_files, pod_meta=pod_meta(booking),
        waybill_ok=waybill_ok, waybill_reason=waybill_reason)


@supplier_bp.route('/booking/<ref>/waybill')
@supplier_required
def legacy_supplier_waybill(ref):
    supplier = get_supplier()
    booking = Booking.query.filter_by(ref=ref, supplier_id=supplier.id).first_or_404()
    ok, reason = can_view_waybill(booking)
    if not ok:
        flash(reason, 'error')
        return redirect(url_for('supplier.booking_documents', ref=ref))
    return render_template('shipper/waybill.html', title=f'Waybill - {ref}', booking=booking)


@supplier_bp.route('/booking/<ref>/pod/<filename>')
@supplier_required
def download_pod_document(ref, filename):
    supplier = get_supplier()
    booking = Booking.query.filter_by(ref=ref, supplier_id=supplier.id).first_or_404()
    safe = secure_filename(filename)
    if safe not in _supplier_pod_files(booking):
        flash('POD document not found for this booking.', 'error')
        return redirect(url_for('supplier.booking_documents', ref=ref))
    path = os.path.abspath(os.path.join('app', 'static', 'pod_photos', safe))
    return send_file(path, as_attachment=True, download_name=safe)


@supplier_bp.route('/booking/<ref>/service-pack')
@supplier_required
def download_service_pack(ref):
    from app.services.evidence_pack import build_service_pack
    supplier = get_supplier()
    booking = Booking.query.filter_by(ref=ref, supplier_id=supplier.id).first_or_404()
    po = _booking_po(booking)
    return send_file(build_service_pack(booking, po), mimetype='application/zip', as_attachment=True,
                     download_name=f'{booking.ref}-proof-of-service-pack.zip')


@supplier_bp.route('/booking/<ref>/service-pack.pdf')
@supplier_required
def download_service_pack_pdf(ref):
    from app.services.evidence_pack import combined_service_pack_pdf
    supplier = get_supplier()
    booking = Booking.query.filter_by(ref=ref, supplier_id=supplier.id).first_or_404()
    po = _booking_po(booking)
    return send_file(io.BytesIO(combined_service_pack_pdf(booking, po)), mimetype='application/pdf', as_attachment=True, download_name=f'{booking.ref}-complete-service-pack.pdf')


# ─────────────────────────────────────────────────────────────────────────────
# Button-level repair endpoint: supplier invoice export
# ─────────────────────────────────────────────────────────────────────────────
@supplier_bp.route("/invoices/export")
@supplier_required
def download_invoice_summary():
    supplier = get_supplier()
    bookings = supplier.bookings.all()
    booking_ids = [b.id for b in bookings]
    invoices = Invoice.query.filter(Invoice.booking_id.in_(booking_ids)).order_by(Invoice.created_at.desc()).all() if booking_ids else []
    import io, csv
    from flask import send_file
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Invoice", "Booking", "Amount", "Status", "Created"])
    for inv in invoices:
        writer.writerow([inv.invoice_number, inv.booking.ref if inv.booking else "", inv.total_amount or inv.amount or 0, inv.status, inv.created_at.strftime("%Y-%m-%d") if inv.created_at else ""])
    return send_file(io.BytesIO(output.getvalue().encode("utf-8")), mimetype="text/csv", as_attachment=True, download_name="supplier-invoices.csv")

# ── Location access approval ─────────────────────────────────────────────────
@supplier_bp.route('/bookings/<ref>/location-access', methods=['POST'])
@supplier_required
def location_access_decision(ref):
    supplier = get_supplier()
    booking = Booking.query.filter_by(ref=ref, supplier_id=supplier.id).first_or_404()
    decision = request.form.get('decision')
    if decision not in ('approve', 'reject'):
        flash('Choose approve or reject for the location request.', 'error')
        return redirect(url_for('supplier.bookings'))
    if decision == 'approve':
        booking.location_access_status = 'Approved'
        booking.location_access_approved_at = datetime.utcnow()
        msg = 'Live driver location access approved until delivery.'
    else:
        booking.location_access_status = 'Rejected'
        msg = 'Live driver location access rejected by supplier. Milestone tracking remains available.'
    db.session.add(BookingStatusEvent(booking_id=booking.id, status=f'Location Access {booking.location_access_status}',
        note=msg, actor=current_user.full_name))
    push_notification(booking.shipper.user_id, f'Location access {booking.location_access_status.lower()} - {booking.ref}',
        msg, type='success' if decision == 'approve' else 'warning', ref_type='booking', ref_id=booking.ref)
    db.session.commit()
    flash(msg, 'success' if decision == 'approve' else 'info')
    return redirect(url_for('supplier.bookings'))

# ═══════════════════════════════════════════════════════════════════════════
# SUPPLIER CONTROL TOWER
# ═══════════════════════════════════════════════════════════════════════════

@supplier_bp.route('/capacity')
@supplier_required
def capacity():
    supplier=get_supplier(); snap=capacity_snapshot(supplier); db.session.commit()
    return render_template('supplier/capacity.html', title='Fleet Capacity', supplier=supplier, snapshot=snap)

@supplier_bp.route('/route-planner')
@supplier_required
def route_planner():
    supplier=get_supplier(); snap=capacity_snapshot(supplier); db.session.commit()
    return render_template('supplier/route_planner.html', title='Route Planner', supplier=supplier, snapshot=snap)

@supplier_bp.route('/return-loads')
@supplier_required
def return_loads():
    supplier=get_supplier(); snap=capacity_snapshot(supplier); rows=[]
    for assignment in snap['return_gaps']:
        rows.append({'assignment':assignment,'matches':return_load_matches(supplier,assignment)[:6]})
    db.session.commit()
    return render_template('supplier/return_loads.html', title='Return Loads', supplier=supplier, rows=rows, settings=snap['settings'])

@supplier_bp.route('/planning-settings', methods=['POST'])
@supplier_required
def planning_settings():
    supplier=get_supplier(); settings=ensure_settings(supplier)
    settings.home_depot_city=request.form.get('home_depot_city', supplier.base_city or 'Durban').strip()
    settings.return_load_radius_km=max(25,int(request.form.get('return_load_radius_km',200)))
    settings.max_deadhead_km=max(25,int(request.form.get('max_deadhead_km',250)))
    settings.turnaround_buffer_minutes=max(0,int(request.form.get('turnaround_buffer_minutes',60)))
    settings.planning_horizon_days=max(1,int(request.form.get('planning_horizon_days',14)))
    db.session.commit(); flash('Route-planning settings updated.','success')
    return redirect(url_for('supplier.return_loads'))

@supplier_bp.route('/trailers', methods=['GET','POST'])
@supplier_required
def trailers():
    supplier=get_supplier()
    if request.method=='POST':
        asset=(request.form.get('asset_number') or '').strip().upper(); reg=(request.form.get('reg_number') or '').strip().upper()
        if not asset or not reg: flash('Asset and registration numbers are required.','error')
        elif Trailer.query.filter_by(supplier_id=supplier.id,asset_number=asset).first(): flash('Trailer asset number already exists.','error')
        else:
            t=Trailer(supplier_id=supplier.id,asset_number=asset,reg_number=reg,trailer_type=request.form.get('trailer_type','General Trailer'),payload_ton=float(request.form.get('payload_ton') or 0),cbm=float(request.form.get('cbm') or 0),current_city=request.form.get('current_city') or supplier.base_city,status=request.form.get('status','Available'))
            for field in ('roadworthy_expiry','licence_expiry','next_service_date'):
                val=request.form.get(field)
                if val: setattr(t,field,date.fromisoformat(val))
            db.session.add(t); db.session.commit(); flash(f'Trailer {asset} added.','success')
        return redirect(url_for('supplier.trailers'))
    items=Trailer.query.filter_by(supplier_id=supplier.id).order_by(Trailer.asset_number).all()
    return render_template('supplier/trailers.html',title='Trailers',supplier=supplier,trailers=items,today=date.today())

@supplier_bp.route('/maintenance', methods=['GET','POST'])
@supplier_required
def maintenance():
    supplier=get_supplier()
    if request.method=='POST':
        kind=request.form.get('asset_kind','Horse'); asset_id=int(request.form.get('asset_id') or 0)
        rec=MaintenanceRecord(supplier_id=supplier.id,asset_kind=kind,vehicle_id=asset_id if kind=='Horse' else None,trailer_id=asset_id if kind=='Trailer' else None,maintenance_type=request.form.get('maintenance_type','Service'),status=request.form.get('status','Scheduled'),scheduled_date=date.fromisoformat(request.form.get('scheduled_date')),notes=request.form.get('notes'))
        db.session.add(rec)
        if kind=='Horse':
            v=Vehicle.query.filter_by(id=asset_id,supplier_id=supplier.id).first_or_404(); v.availability='Maintenance'
        else:
            t=Trailer.query.filter_by(id=asset_id,supplier_id=supplier.id).first_or_404(); t.status='Maintenance'
        db.session.commit(); flash('Maintenance booking created and asset capacity blocked.','success')
        return redirect(url_for('supplier.maintenance'))
    records=MaintenanceRecord.query.filter_by(supplier_id=supplier.id).order_by(MaintenanceRecord.created_at.desc()).all()
    return render_template('supplier/maintenance.html',title='Maintenance',supplier=supplier,records=records,vehicles=supplier.vehicles.all(),trailers=Trailer.query.filter_by(supplier_id=supplier.id).all())

@supplier_bp.route('/return-loads/<int:assignment_id>/secure/<int:booking_id>', methods=['POST'])
@supplier_required
def secure_return_load(assignment_id, booking_id):
    supplier=get_supplier()
    a=FleetAssignment.query.filter_by(id=assignment_id,supplier_id=supplier.id).first_or_404()
    b=Booking.query.get_or_404(booking_id)
    valid = next((m for m in return_load_matches(supplier, a) if m['booking'].id == b.id), None)
    if not valid:
        flash('That load is no longer eligible for this truck or is outside its 200 km search zone.','error')
        return redirect(url_for('supplier.return_loads'))
    a.return_load_status='Secured'
    a.next_booking_id=b.id
    db.session.add(BookingStatusEvent(booking_id=a.booking_id,status='Return Load Secured',note=f'{a.vehicle.reg_number} reserved next-load opportunity {b.ref}; pickup is {valid["collection_distance"]} km from its projected drop-off.',actor=current_user.full_name))
    db.session.add(BookingStatusEvent(booking_id=b.id,status='Reserved as Return Load',note=f'Reserved as the next planned load for {a.vehicle.reg_number}, available {a.available_at}.',actor=current_user.full_name))
    db.session.commit()
    flash(f'{b.ref} reserved as the next job for {a.vehicle.reg_number}.','success')
    return redirect(url_for('supplier.return_loads'))
