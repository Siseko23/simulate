"""
Admin blueprint - platform oversight, approvals, analytics, user management.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import login_required, current_user
from functools import wraps
from datetime import datetime, date, timedelta
import io, csv, os

from app.models import (db, User, Booking, Quote, SupplierProfile, ShipperProfile,
                         Driver, Vehicle, Invoice, PurchaseOrder,
                         Notification, AuditLog, SupplierScoreHistory,
                         ComplianceDocument, DocumentRequest, Payout, AdminAccount,
                         PlatformSettings, AISettings, Complaint, ComplaintMessage)
from app.services.notifications import push_notification
from app.services.v19_adapter import booking_to_v19, supplier_to_v19
from app.services.audit import log_action
from app.services.lifecycle import admin_can_force_status
from app.services.finance import can_approve_po, can_release_payout, log_finance_event

admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if current_user.role != "admin":
            flash("Access denied.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ─────────────────────────────────────────────────────────────────

@admin_bp.route("/")
@admin_required
def dashboard():
    total_bookings  = Booking.query.count()
    active          = Booking.query.filter(
                        Booking.status.in_(["Confirmed","Driver Assigned","Collected","In Transit"])).count()
    delivered_today = Booking.query.filter(
                        Booking.status=="Delivered",
                        db.func.date(Booking.delivered_at)==date.today()).count()
    pending_approval= SupplierProfile.query.filter_by(status="Under Review").count()
    total_suppliers = SupplierProfile.query.filter_by(status="Active").count()
    total_shippers  = ShipperProfile.query.count()
    platform_revenue= db.session.query(db.func.sum(Booking.platform_fee)).scalar() or 0
    recent_bookings = Booking.query.order_by(Booking.created_at.desc()).limit(10).all()
    recent_logs     = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(15).all()

    # Build v19 notification console items
    from app.models import Notification, User as _User
    admin_notifs = []
    for log in recent_logs[:5]:
        u = _User.query.get(log.user_id) if log.user_id else None
        admin_notifs.append({
            "title": f"{log.action} - {log.entity_id or ''}",
            "detail": log.detail or "",
            "audience": log.entity_type or "System",
            "channel": "Platform",
            "time": log.created_at.strftime("%H:%M") if log.created_at else "",
        })
    return render_template("admin/dashboard.html",
        title="Platform Overview",
        total_bookings=total_bookings, active=active,
        delivered_today=delivered_today, pending_approval=pending_approval,
        total_suppliers=total_suppliers, total_shippers=total_shippers,
        platform_revenue=platform_revenue,
        recent_bookings=[booking_to_v19(b) for b in recent_bookings],
        recent_logs=recent_logs,
        notifications=admin_notifs)


# ── Bookings ──────────────────────────────────────────────────────────────────

@admin_bp.route("/bookings")
@admin_required
def bookings():
    status = request.args.get("status","")
    q      = request.args.get("q","")
    query  = Booking.query.order_by(Booking.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    if q:
        query = query.filter(Booking.ref.ilike(f"%{q}%") | Booking.route.ilike(f"%{q}%"))
    bookings = query.limit(200).all()
    return render_template("admin/bookings.html",
        title="All Bookings",
        bookings=[booking_to_v19(b) for b in bookings],
        status_filter=status, search=q)


@admin_bp.route("/bookings/<ref>/force-status", methods=["POST"])
@admin_required
def force_status(ref):
    booking    = Booking.query.filter_by(ref=ref).first_or_404()
    new_status = request.form.get("status")
    note       = request.form.get("note","Admin override")
    ok, reason = admin_can_force_status(new_status)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("admin.bookings"))
    booking.status = new_status
    from app.models import BookingStatusEvent
    event = BookingStatusEvent(booking_id=booking.id, status=new_status,
                                note=note, actor=f"ADMIN:{current_user.full_name}")
    db.session.add(event)
    db.session.commit()
    log_action(current_user.id, "FORCE_STATUS", "Booking", ref, f"-> {new_status}")
    flash(f"Booking {ref} status set to {new_status}.", "success")
    return redirect(url_for("admin.bookings"))


# ── Supplier Management ───────────────────────────────────────────────────────

@admin_bp.route("/suppliers")
@admin_required
def suppliers():
    status = request.args.get("status","")
    query  = SupplierProfile.query
    if status:
        query = query.filter_by(status=status)
    suppliers = query.order_by(SupplierProfile.created_at.desc()).all()
    return render_template("admin/approvals.html",
        title="Supplier Approvals",
        suppliers=suppliers, status_filter=status)


@admin_bp.route("/suppliers/<int:sid>/approve", methods=["POST"])
@admin_required
def approve_supplier(sid):
    supplier = SupplierProfile.query.get_or_404(sid)
    supplier.status      = "Active"
    supplier.approved_at = datetime.utcnow()
    push_notification(supplier.user_id,
                      "Your supplier account is approved! Success",
                      "You can now receive booking requests on FreightFlow Nexus.",
                      type="success")
    db.session.commit()
    log_action(current_user.id, "APPROVE_SUPPLIER", "SupplierProfile", str(sid))
    flash(f"{supplier.company_name} approved.", "success")
    return redirect(url_for("admin.suppliers"))


@admin_bp.route("/suppliers/<int:sid>/suspend", methods=["POST"])
@admin_required
def suspend_supplier(sid):
    supplier        = SupplierProfile.query.get_or_404(sid)
    reason          = request.form.get("reason","Score below threshold")
    supplier.status = "Suspended"
    push_notification(supplier.user_id,
                      "Your supplier account has been suspended",
                      f"Reason: {reason}. Contact support@movement.com to appeal.",
                      type="error")
    db.session.commit()
    log_action(current_user.id, "SUSPEND_SUPPLIER", "SupplierProfile", str(sid), reason)
    flash(f"{supplier.company_name} suspended.", "warning")
    return redirect(url_for("admin.suppliers"))


@admin_bp.route("/suppliers/<int:sid>")
@admin_required
def supplier_detail(sid):
    # NOTE: admin/supplier_insights.html is a large pre-built dashboard template
    # designed for a rich multi-supplier analytics dataset (score trajectories,
    # fleet utilisation, doc expiry tracking, financial drill-downs) that does
    # not exist in the current data model. No template currently links here.
    # Redirecting to supplier-risk (the real, working supplier analytics page)
    # until this view is properly built out with full supporting data.
    flash("Detailed supplier insights are coming soon - showing supplier risk overview instead.", "info")
    return redirect(url_for("admin.supplier_risk"))


# ── Shipper Management ────────────────────────────────────────────────────────

@admin_bp.route("/shippers")
@admin_required
def shippers():
    shippers = ShipperProfile.query.order_by(ShipperProfile.created_at.desc()).all()
    return render_template("admin/shipping_agents.html",
        title="Shippers", shippers=shippers)


# ── User Management ───────────────────────────────────────────────────────────

@admin_bp.route("/users")
@admin_required
def users():
    role  = request.args.get("role","")
    query = User.query
    if role:
        query = query.filter_by(role=role)
    users = query.order_by(User.created_at.desc()).all()
    return render_template("admin/admins.html",
        title="Users", users=users, role_filter=role)


@admin_bp.route("/users/<int:uid>/toggle", methods=["POST"])
@admin_required
def toggle_user(uid):
    user = User.query.get_or_404(uid)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("admin.users"))
    user.is_active = not user.is_active
    db.session.commit()
    state = "activated" if user.is_active else "deactivated"
    log_action(current_user.id, f"USER_{state.upper()}", "User", str(uid))
    flash(f"User {user.email} {state}.", "info")
    return redirect(url_for("admin.users"))


# ── Marketplace Intelligence ──────────────────────────────────────────────────

@admin_bp.route("/marketplace")
@admin_required
def marketplace():
    # Real aggregated route data from bookings
    from sqlalchemy import func
    route_data = db.session.query(
        Booking.route,
        func.count(Booking.id).label("volume"),
        func.avg(Booking.quoted_value).label("avg_rate"),
        func.sum(Booking.quoted_value).label("total_value"),
    ).filter(Booking.status == "Delivered")\
     .group_by(Booking.route)\
     .order_by(func.count(Booking.id).desc())\
     .limit(10).all()

    total_volume    = sum(r.volume for r in route_data)
    platform_revenue= db.session.query(func.sum(Booking.platform_fee)).scalar() or 0
    total_bookings  = Booking.query.count()

    # Supplier market share
    supplier_share = db.session.query(
        SupplierProfile.company_name,
        func.count(Booking.id).label("bookings"),
    ).join(Booking, Booking.supplier_id == SupplierProfile.id)\
     .group_by(SupplierProfile.id)\
     .order_by(func.count(Booking.id).desc()).limit(5).all()

    avg_platform_rate = int(sum(r.avg_rate or 0 for r in route_data) / len(route_data)) if route_data else 0

    return render_template("admin/marketplace.html",
        title="Marketplace Intelligence",
        route_data=route_data, total_volume=total_volume,
        platform_revenue=platform_revenue, total_bookings=total_bookings,
        supplier_share=supplier_share, avg_platform_rate=avg_platform_rate,
        routes=[{"route": r.route, "volume": r.volume, "avgRate": r.avg_rate or 0,
                 "currentAvg": r.avg_rate or 0, "demand": "High" if r.volume > 20 else "Medium",
                 "priceChange": 2.1, "topSupplier": "-", "trend": "up"} for r in route_data])


# ── Supplier Risk Monitor ─────────────────────────────────────────────────────

@admin_bp.route("/supplier-risk")
@admin_required
def supplier_risk():
    suppliers = SupplierProfile.query.filter_by(status="Active").all()
    risk_data = []
    for sup in suppliers:
        hist  = sup.score_history.order_by(SupplierScoreHistory.recorded_at).all()
        traj  = [h.score for h in hist[-6:]] if hist else [sup.score]
        delta = round(traj[-1] - traj[0], 2) if len(traj) >= 2 else 0

        if sup.score < 3.5 or delta < -0.5:  risk = "High"
        elif sup.score < 4.0 or delta < -0.2: risk = "Medium"
        else:                                   risk = "Low"

        risk_data.append({
            "id":            sup.id,
            "name":          sup.company_name,
            "baseCity":      sup.base_city or "",
            "status":        sup.status,
            "score":         sup.score,
            "scoreChange":   delta,
            "onTimeRate":    sup.on_time_rate,
            "cancelRate":    sup.cancellation_rate,
            "totalJobs":     sup.total_jobs,
            "trajectory":    traj,
            "risk":          risk,
            "supplier":      sup,
            # Nested stats dict used by template as s.stats.acceptanceRate
            "stats": {
                "acceptanceRate":    sup.acceptance_rate,
                "onTimeRate":        sup.on_time_rate,
                "cancellationRate":  sup.cancellation_rate,
                "totalJobs":         sup.total_jobs,
                "rejectionRate":     round(100 - sup.acceptance_rate, 1),
            },
        })
    risk_data.sort(key=lambda x: {"High":0,"Medium":1,"Low":2}[x["risk"]])
    return render_template("admin/supplier_risk.html",
        title="Supplier Risk Monitor", risk_data=risk_data)


# ── Executive Reports ─────────────────────────────────────────────────────────

@admin_bp.route("/reports")
@admin_bp.route("/executive-reports")
@admin_required
def executive_reports():
    from sqlalchemy import func
    total_revenue   = db.session.query(func.sum(Booking.quoted_value)).scalar() or 0
    platform_fees   = db.session.query(func.sum(Booking.platform_fee)).scalar() or 0
    supplier_payouts= db.session.query(func.sum(Booking.supplier_payout)).scalar() or 0
    total_bookings  = Booking.query.count()
    total_shippers  = ShipperProfile.query.count()
    total_suppliers = SupplierProfile.query.filter_by(status="Active").count()
    return render_template("admin/executive_reports.html",
        title="Executive Reports",
        total_revenue=total_revenue,
        platform_fee_total=platform_fees,  # template uses platform_fee_total
        platform_fees=platform_fees,
        supplier_payouts=supplier_payouts, total_bookings=total_bookings,
        total_shippers=total_shippers, total_suppliers=total_suppliers,
        reports=[
            {"id":"RPT-001","title":"Monthly Logistics - June 2026","type":"monthly","generated":"01 Jun 2026","size":"2.4 MB"},
            {"id":"RPT-002","title":"Supplier Performance - Q2 2026","type":"supplier","generated":"01 Jun 2026","size":"1.8 MB"},
            {"id":"RPT-003","title":"Financial Summary - May 2026","type":"financial","generated":"01 May 2026","size":"0.9 MB"},
        ])


@admin_bp.route("/executive-reports/export-csv")
@admin_required
def export_bookings_csv():
    bookings = Booking.query.order_by(Booking.created_at.desc()).all()
    output   = io.StringIO()
    writer   = csv.writer(output)
    writer.writerow(["Ref","Route","Shipper","Supplier","Status","Value","Platform Fee",
                      "Supplier Payout","Collection Date","Created"])
    for b in bookings:
        writer.writerow([
            b.ref, b.route,
            b.shipper.user.full_name if b.shipper else "",
            b.supplier.company_name if b.supplier else "",
            b.status, f"{b.quoted_value:.2f}", f"{b.platform_fee:.2f}",
            f"{b.supplier_payout:.2f}",
            str(b.collection_date or ""), str(b.created_at)[:10]
        ])
    output.seek(0)
    log_action(current_user.id, "EXPORT_CSV", "Booking", "ALL")
    return send_file(
        io.BytesIO(output.read().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"ffn_bookings_{date.today()}.csv"
    )


# ── Audit Log ─────────────────────────────────────────────────────────────────

@admin_bp.route("/audit-log")
@admin_required
def audit_log():
    logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template("admin/audit_log.html",
        title="Audit Log", logs=logs)


# ── Complaints ─────────────────────────────────────────────────────────────────

from app.models import Complaint  # local import

@admin_bp.route("/complaints")
@admin_required
def complaints():
    status_filter = request.args.get("status", "")
    q = Complaint.query
    if status_filter:
        q = q.filter_by(status=status_filter)
    all_complaints = q.order_by(Complaint.created_at.desc()).all()
    status_options = ["Submitted", "Under Admin Review", "Forwarded to Supplier",
                      "Supplier Responded", "Resolved", "Closed"]
    counts = {s: Complaint.query.filter_by(status=s).count() for s in status_options}
    return render_template("admin/complaints.html",
        title="Complaints", complaints=all_complaints,
        status_filter=status_filter, status_options=status_options, counts=counts)


@admin_bp.route("/complaints/<ref>", methods=["GET", "POST"])
@admin_required
def complaint_detail(ref):
    c = Complaint.query.filter_by(ref=ref).first_or_404()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "update_notes":
            c.admin_notes = request.form.get("admin_notes", "").strip()
            c.status = "Under Admin Review"
            db.session.commit()
            flash("Notes saved.", "success")

        elif action == "reply":
            msg = request.form.get("message", "").strip()
            if msg:
                db.session.add(ComplaintMessage(
                    complaint_id=c.id, sender_role="support",
                    sender_name=current_user.full_name, text=msg))
                if c.status == "Submitted":
                    c.status = "Under Admin Review"
                db.session.commit()
                push_notification(c.shipper.user_id,
                    f"Reply on complaint {c.ref}",
                    f"FreightFlow support has replied to your complaint: \"{msg[:80]}\"",
                    type="info", ref_type="complaint", ref_id=c.ref)
                flash("Reply sent to shipper.", "success")

        elif action == "assign":
            agent_id = request.form.get("agent_id", type=int)
            if agent_id:
                c.assigned_agent_id = agent_id
                db.session.commit()
                agent = User.query.get(agent_id)
                flash(f"Assigned to {agent.full_name if agent else 'agent'}.", "success")

        elif action == "escalate":
            c.priority = "Critical"
            if c.status not in ("Resolved", "Closed"):
                c.status = "Under Admin Review"
            db.session.add(ComplaintMessage(
                complaint_id=c.id, sender_role="system", sender_name="FreightFlow System",
                text=f"Complaint escalated to Critical priority by {current_user.full_name}."))
            db.session.commit()
            log_action(current_user.id, "complaint_escalated", "complaint", c.ref)
            flash(f"Complaint {c.ref} escalated to Critical.", "warning")

        elif action == "forward":
            # Forward complaint to supplier
            c.status       = "Forwarded to Supplier"
            c.forwarded_at = datetime.utcnow()
            c.forwarded_by_id = current_user.id
            c.admin_notes  = request.form.get("admin_notes", c.admin_notes or "").strip()
            db.session.add(ComplaintMessage(
                complaint_id=c.id, sender_role="system", sender_name="FreightFlow System",
                text=f"Complaint forwarded to {c.supplier.company_name if c.supplier else 'supplier'} for response."))
            db.session.commit()

            # Notify supplier
            if c.supplier:
                push_notification(
                    c.supplier.user_id,
                    f"Complaint {c.ref} - action required",
                    f"A complaint has been reviewed by admin and forwarded to you. Category: {c.category}. Please respond within 4 hours.",
                    type="error", ref_type="complaint", ref_id=c.ref)

            # Notify shipper
            push_notification(
                c.shipper.user_id,
                f"Complaint {c.ref} forwarded to supplier",
                "Our support team has reviewed your complaint and forwarded it to the supplier for their response.",
                type="info", ref_type="complaint", ref_id=c.ref)

            log_action(current_user.id, "complaint_forwarded", "complaint", c.ref,
                       f"Forwarded {c.ref} to supplier {c.supplier.company_name if c.supplier else 'N/A'}")
            flash(f"Complaint {c.ref} forwarded to supplier.", "success")

        elif action == "resolve":
            c.status           = "Resolved"
            c.resolution_notes = request.form.get("resolution_notes", "").strip()
            c.resolved_at      = datetime.utcnow()
            db.session.commit()

            push_notification(c.shipper.user_id,
                f"Complaint {c.ref} resolved",
                c.resolution_notes or "Your complaint has been resolved by our support team.",
                type="success", ref_type="complaint", ref_id=c.ref)
            flash("Complaint marked as resolved.", "success")

        elif action == "close":
            c.status = "Closed"
            db.session.commit()
            flash("Complaint closed.", "info")

        return redirect(url_for("admin.complaint_detail", ref=ref))

    support_agents = User.query.join(AdminAccount).filter(
        AdminAccount.department.in_(["support", "superadmin"])).all()
    return render_template("admin/complaint_detail.html", title=f"Complaint {ref}",
        complaint=c, support_agents=support_agents)


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN ACCOUNTS (department management - superadmin only can add)
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route("/admins")
@admin_required
def admins():
    accounts = AdminAccount.query.join(User).order_by(AdminAccount.created_at).all()
    my_account = AdminAccount.query.filter_by(user_id=current_user.id).first()
    current_admin_role = my_account.department if my_account else "support"
    departments = [
        {"id": k, "name": v["name"], "icon": v["icon"], "permissions": _dept_permissions(k)}
        for k, v in AdminAccount.DEPARTMENTS.items()
    ]
    return render_template("admin/admins.html",
        title="Admin accounts", accounts=accounts, departments=departments,
        current_admin_role=current_admin_role,
        dept_names={k: v["name"] for k, v in AdminAccount.DEPARTMENTS.items()})


def _dept_permissions(dept):
    return {
        "superadmin": ["Full platform access", "All departments", "System settings", "Create/deactivate admins"],
        "finance":    ["Supplier payouts", "Excel reports", "Transaction ledger", "Banking verification"],
        "support":    ["Customer reports", "Dispute resolution", "Shipper/supplier notifications", "On-call escalations"],
        "compliance": ["Supplier document review", "Document requests", "Supplier approvals", "License tracking"],
        "operations": ["Booking oversight", "AI engine settings", "Supplier performance", "Driver management"],
    }.get(dept, [])


@admin_bp.route("/admins/add", methods=["POST"])
@admin_required
def add_admin():
    my_account = AdminAccount.query.filter_by(user_id=current_user.id).first()
    if not my_account or my_account.department != "superadmin":
        flash("Only the super admin can create new admin accounts.", "error")
        return redirect(url_for("admin.admins"))

    name       = request.form.get("name", "").strip()
    email      = request.form.get("email", "").strip().lower()
    department = request.form.get("department", "support")
    password   = request.form.get("password", "")

    if not name or not email or not password:
        flash("All fields are required.", "error")
        return redirect(url_for("admin.admins"))
    if User.query.filter_by(email=email).first():
        flash("An account with that email already exists.", "error")
        return redirect(url_for("admin.admins"))

    parts = name.split(" ", 1)
    first, last = parts[0], (parts[1] if len(parts) > 1 else "")
    u = User(email=email, role="admin", first_name=first, last_name=last)
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    db.session.add(AdminAccount(user_id=u.id, department=department))
    db.session.commit()

    log_action(current_user.id, "ADMIN_ACCOUNT_CREATED", "User", str(u.id), f"{name} ({department})")
    flash(f"Admin account created for {name}.", "success")
    return redirect(url_for("admin.admins"))


@admin_bp.route("/admins/<int:admin_id>/deactivate", methods=["POST"])
@admin_required
def deactivate_admin(admin_id):
    my_account = AdminAccount.query.filter_by(user_id=current_user.id).first()
    if not my_account or my_account.department != "superadmin":
        flash("Only the super admin can deactivate admin accounts.", "error")
        return redirect(url_for("admin.admins"))

    acc = AdminAccount.query.get_or_404(admin_id)
    if acc.user_id == current_user.id:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("admin.admins"))

    acc.is_active = False
    acc.deactivated_at = datetime.utcnow()
    acc.user.is_active = False
    db.session.commit()
    log_action(current_user.id, "ADMIN_ACCOUNT_DEACTIVATED", "User", str(acc.user_id))
    flash(f"{acc.user.full_name}'s admin account has been deactivated.", "info")
    return redirect(url_for("admin.admins"))


# ═══════════════════════════════════════════════════════════════════════════
# DOCUMENT VERIFICATION (compliance - review supplier compliance docs)
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route("/documents")
@admin_required
def documents():
    supplier_id = request.args.get("supplier_id", type=int)
    # Build supplier list with doc stats
    all_suppliers = SupplierProfile.query.order_by(SupplierProfile.company_name).all()
    supplier_stats = []
    for s in all_suppliers:
        docs = s.documents.all()
        pending  = sum(1 for d in docs if d.status == "Pending review")
        verified = sum(1 for d in docs if d.status == "Verified")
        expiring = sum(1 for d in docs if d.expiry_date and d.days_to_expiry is not None and 0 <= d.days_to_expiry <= 30)
        expired  = sum(1 for d in docs if d.expiry_date and d.days_to_expiry is not None and d.days_to_expiry < 0)
        supplier_stats.append({
            "id": s.id, "name": s.company_name,
            "status": s.status, "total": len(docs),
            "pending": pending, "verified": verified,
            "expiring": expiring, "expired": expired,
        })

    selected_supplier = None
    docs = []
    if supplier_id:
        selected_supplier = SupplierProfile.query.get_or_404(supplier_id)
        docs = selected_supplier.documents.order_by(
            ComplianceDocument.uploaded_at.desc()).all()

    pending_count = ComplianceDocument.query.filter_by(status="Pending review").count()
    return render_template("admin/documents.html",
        title="Document verification",
        supplier_stats=supplier_stats,
        selected_supplier=selected_supplier,
        documents=docs,
        supplier_id=supplier_id,
        pending_count=pending_count)


@admin_bp.route("/documents/<int:doc_id>/verify", methods=["POST"])
@admin_required
def verify_document(doc_id):
    doc = ComplianceDocument.query.get_or_404(doc_id)
    doc.status = "Verified"
    doc.verified_at = datetime.utcnow()
    doc.verified_by_id = current_user.id
    db.session.commit()

    push_notification(doc.supplier.user_id,
        f"Document verified - {doc.name}",
        f"Your {doc.name} has been verified by FreightFlow compliance.",
        type="success", ref_type="document", ref_id=str(doc.id))
    log_action(current_user.id, "DOCUMENT_VERIFIED", "ComplianceDocument", str(doc.id))
    flash(f"{doc.name} verified for {doc.supplier.company_name}.", "success")
    next_url = request.form.get("next") or url_for("admin.documents", supplier_id=doc.supplier_id)
    return redirect(next_url)


@admin_bp.route("/documents/<int:doc_id>/reject", methods=["POST"])
@admin_required
def reject_document(doc_id):
    doc = ComplianceDocument.query.get_or_404(doc_id)
    reason = request.form.get("reason", "").strip()
    doc.status = "Awaiting re-upload"
    doc.rejection_reason = reason or "Document did not meet requirements."
    db.session.commit()

    push_notification(doc.supplier.user_id,
        f"Document rejected - {doc.name}",
        f"Your {doc.name} was rejected: {doc.rejection_reason} Please re-upload.",
        type="error", ref_type="document", ref_id=str(doc.id))
    log_action(current_user.id, "DOCUMENT_REJECTED", "ComplianceDocument", str(doc.id), reason)
    flash(f"{doc.name} rejected - supplier notified to re-upload.", "info")
    next_url = request.form.get("next") or url_for("admin.documents", supplier_id=doc.supplier_id)
    return redirect(next_url)


@admin_bp.route("/documents/<int:doc_id>/download")
@admin_required
def download_document(doc_id):
    doc = ComplianceDocument.query.get_or_404(doc_id)
    filename = doc.filename
    if filename:
        path = os.path.abspath(os.path.join("app", "static", "supplier_documents", filename))
        if os.path.exists(path):
            return send_file(path, as_attachment=False, download_name=filename)
    content = (
        "FreightFlow Nexus Compliance Document\n"
        f"Document: {doc.name}\n"
        f"Supplier: {doc.supplier.company_name if doc.supplier else '-'}\n"
        f"Status: {doc.status}\n"
        f"Filename: {filename or 'No uploaded file found'}\n"
        f"Uploaded: {doc.uploaded_at.strftime('%Y-%m-%d %H:%M') if doc.uploaded_at else '-'}\n"
    )
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/plain",
                     as_attachment=False, download_name=f"compliance-document-{doc.id}.txt")


# ═══════════════════════════════════════════════════════════════════════════
# DOCUMENT REQUESTS (compliance follow-ups with deadlines)
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route("/doc-requests")
@admin_required
def doc_requests():
    # Auto-flag overdue requests
    overdue = DocumentRequest.query.filter(
        DocumentRequest.status == "Pending",
        DocumentRequest.deadline < date.today()
    ).all()
    for req_ in overdue:
        req_.status = "Overdue"
    if overdue:
        db.session.commit()

    requests_list = DocumentRequest.query.join(SupplierProfile).order_by(DocumentRequest.sent_at.desc()).all()
    suppliers = SupplierProfile.query.filter_by(status="Active").all()
    return render_template("admin/doc_requests.html",
        title="Document requests", requests=requests_list, suppliers=suppliers,
        today_iso=date.today().isoformat(),
        default_deadline_iso=(date.today() + timedelta(days=14)).isoformat())


@admin_bp.route("/doc-requests/send", methods=["POST"])
@admin_required
def send_doc_request():
    supplier_id = request.form.get("supplier_id", type=int)
    doc_type    = request.form.get("doc_type", "").strip()
    deadline_str = request.form.get("deadline", "")
    overdue_action = request.form.get("overdue_action", "suspend")

    supplier = SupplierProfile.query.get_or_404(supplier_id)
    try:
        deadline = date.fromisoformat(deadline_str)
    except ValueError:
        deadline = date.today() + timedelta(days=14)

    req_ = DocumentRequest(supplier_id=supplier.id, doc_type=doc_type,
                            deadline=deadline, overdue_action=overdue_action)
    db.session.add(req_)
    db.session.commit()

    push_notification(supplier.user_id,
        f"Document required - {doc_type}",
        f"Please upload your {doc_type} by {deadline.strftime('%d %b %Y')}. "
        f"{'Failure to comply may result in suspension.' if overdue_action=='suspend' else ''}",
        type="warning", ref_type="document_request", ref_id=str(req_.id))
    log_action(current_user.id, "DOC_REQUEST_SENT", "DocumentRequest", str(req_.id),
               f"{doc_type} requested from {supplier.company_name}")
    flash(f"Document request sent to {supplier.company_name}.", "success")
    return redirect(url_for("admin.doc_requests"))


# ═══════════════════════════════════════════════════════════════════════════
# PAYOUTS (finance - pay suppliers for completed bookings)
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route("/payouts")
@admin_required
def payouts():
    """Finance overview: only approved, unpaid POs are payable.

This prevents paying suppliers simply because a booking says Delivered.
The supplier must upload an invoice and finance must verify it first.
    """
    approved_pos = PurchaseOrder.query.filter_by(status="Approved").all()
    owed_by_supplier = {}
    for po in approved_pos:
        b = po.booking
        sp = b.supplier if b else None
        if not sp or po.paid_at:
            continue
        item = owed_by_supplier.setdefault(sp.id, {
            "supplier": sp, "amount": 0, "bookings_count": 0,
            "banking_complete": bool(sp.bank_name and sp.bank_account),
            "po_ids": []
        })
        item["amount"] += po.net_payable or 0
        item["bookings_count"] += 1
        item["po_ids"].append(po.id)
    owed = list(owed_by_supplier.values())
    history = Payout.query.order_by(Payout.paid_at.desc()).limit(30).all()
    total_pending = sum(o["amount"] for o in owed)
    return render_template("admin/payouts.html",
        title="Supplier payouts", owed=owed, history=history, total_pending=total_pending)


@admin_bp.route("/payouts/<int:supplier_id>/pay", methods=["POST"])
@admin_required
def pay_supplier(supplier_id):
    sp = SupplierProfile.query.get_or_404(supplier_id)
    approved_pos = PurchaseOrder.query.join(Booking).filter(
        Booking.supplier_id == sp.id,
        PurchaseOrder.status == "Approved",
        PurchaseOrder.paid_at.is_(None)
    ).all()
    amount = sum((po.net_payable or 0) for po in approved_pos)

    if amount <= 0 or not approved_pos:
        flash(f"No approved, unpaid PO payout for {sp.company_name}.", "info")
        return redirect(url_for("admin.payouts"))
    if not (sp.bank_name and sp.bank_account):
        flash(f"{sp.company_name} has incomplete banking details - cannot process payout.", "error")
        return redirect(url_for("admin.payouts"))

    p = Payout(supplier_id=sp.id, amount=amount, bookings_count=len(approved_pos),
               bank_summary=f"{sp.bank_name.split('(')[0].strip()} ···{sp.bank_account[-4:]}",
               paid_by_id=current_user.id)
    p.generate_ref()
    db.session.add(p)
    now = datetime.utcnow()
    for po in approved_pos:
        po.status = "Paid"
        po.paid_at = now
        log_finance_event(po.booking, "Supplier Paid",
            f"Supplier payout released via {p.payout_ref}. Net payout: R{po.net_payable:,.2f}.",
            current_user.full_name)
    db.session.commit()

    push_notification(sp.user_id, f"Payout processed - R{amount:,.2f}",
        f"A payout of R{amount:,.2f} for {len(approved_pos)} verified PO(s) has been sent to your bank account.",
        type="success", ref_type="payout", ref_id=p.payout_ref)
    log_action(current_user.id, "SUPPLIER_PAID", "SupplierProfile", str(sp.id), f"R{amount:,.2f}")
    flash(f"Paid R{amount:,.2f} to {sp.company_name} for verified PO(s).", "success")
    return redirect(url_for("admin.payouts"))


# ═══════════════════════════════════════════════════════════════════════════
# PLATFORM & AI SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    s = PlatformSettings.get()
    if request.method == "POST":
        s.volumetric_divisor = request.form.get("volumetric_divisor", type=int) or s.volumetric_divisor
        s.platform_fee_pct   = request.form.get("platform_fee_pct", type=float) or s.platform_fee_pct
        s.commission_pct     = request.form.get("commission_pct", type=float) or s.commission_pct
        db.session.commit()
        log_action(current_user.id, "PLATFORM_SETTINGS_UPDATED", "PlatformSettings", str(s.id))
        flash("Platform settings updated.", "success")
        return redirect(url_for("admin.settings"))
    return render_template("admin/settings.html", title="Platform settings", settings=s)


@admin_bp.route("/ai-settings", methods=["GET", "POST"])
@admin_required
def ai_settings():
    s = AISettings.get()
    if request.method == "POST":
        s.proximity_radius_km          = request.form.get("proximity_radius_km", type=int) or s.proximity_radius_km
        s.price_weight                 = request.form.get("price_weight", type=int) or s.price_weight
        s.performance_weight           = request.form.get("performance_weight", type=int) or s.performance_weight
        s.proximity_weight             = request.form.get("proximity_weight", type=int) or s.proximity_weight
        s.min_performance_score        = request.form.get("min_performance_score", type=float) or s.min_performance_score
        s.supplier_response_window_hrs = request.form.get("supplier_response_window_hrs", type=int) or s.supplier_response_window_hrs
        db.session.commit()
        log_action(current_user.id, "AI_SETTINGS_UPDATED", "AISettings", str(s.id))
        flash("AI matching settings updated.", "success")
        return redirect(url_for("admin.ai_settings"))
    return render_template("admin/ai_settings.html", title="AI engine settings", settings=s)


# ═══════════════════════════════════════════════════════════════════════════
# SHIPPING AGENTS
# ═══════════════════════════════════════════════════════════════════════════

# Simple in-memory store (replace with DB model in future)
_agents = {}  # id -> dict

@admin_bp.route("/shipping-agents")
@admin_required
def shipping_agents():
    agents = list(_agents.values())
    return render_template("admin/shipping_agents.html", title="Shipping Agents", agents=agents)

@admin_bp.route("/shipping-agents/add", methods=["GET","POST"])
@admin_required
def shipping_agent_add():
    if request.method == "POST":
        import uuid
        aid = str(uuid.uuid4())[:8].upper()
        _agents[aid] = {
            "id": aid,
            "name":        request.form.get("name","").strip(),
            "email":       request.form.get("email","").strip(),
            "phone":       request.form.get("phone","").strip(),
            "company":     request.form.get("company","").strip(),
            "regions":     request.form.get("regions","").strip(),
            "commission":  request.form.get("commission","5"),
            "status":      "Pending",
            "created_at":  datetime.utcnow().strftime("%d %b %Y"),
        }
        flash(f"Agent {request.form.get('name')} registered - pending approval.", "success")
        return redirect(url_for("admin.shipping_agents"))
    return render_template("admin/shipping_agent_add.html", title="Add Shipping Agent")

@admin_bp.route("/shipping-agents/<aid>/approve", methods=["POST"])
@admin_required
def approve_shipping_agent(aid):
    if aid in _agents:
        _agents[aid]["status"] = "Active"
        flash(f"Agent {_agents[aid]['name']} approved and activated.", "success")
    return redirect(url_for("admin.shipping_agent_detail", aid=aid))

@admin_bp.route("/shipping-agents/<aid>/suspend", methods=["POST"])
@admin_required
def suspend_shipping_agent(aid):
    if aid in _agents:
        _agents[aid]["status"] = "Suspended"
        flash(f"Agent suspended.", "info")
    return redirect(url_for("admin.shipping_agent_detail", aid=aid))

@admin_bp.route("/shipping-agents/<aid>/reinstate", methods=["POST"])
@admin_required
def reinstate_shipping_agent(aid):
    if aid in _agents:
        _agents[aid]["status"] = "Active"
        flash(f"Agent reinstated.", "success")
    return redirect(url_for("admin.shipping_agent_detail", aid=aid))

@admin_bp.route("/shipping-agents/<aid>")
@admin_required
def shipping_agent_detail(aid):
    agent = _agents.get(aid)
    if not agent:
        flash("Agent not found.", "error")
        return redirect(url_for("admin.shipping_agents"))
    return render_template("admin/shipping_agent_detail.html", title="Agent detail", agent=agent)


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN CONTAINER QUOTE APPROVAL
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route("/container-quotes/<int:qid>/approve", methods=["POST"])
@admin_required
def approve_container_quote(qid):
    from app.models import RateCard
    rc = RateCard.query.get_or_404(qid)
    rc.is_active = True
    db.session.commit()
    flash(f"Container quote approved and now visible to shippers.", "success")
    log_action(current_user.id, "CQ_APPROVED", "RateCard", str(qid), "")
    return redirect(url_for("admin.container_quotes_admin"))

@admin_bp.route("/container-quotes/<int:qid>/reject", methods=["POST"])
@admin_required
def reject_container_quote(qid):
    from app.models import RateCard
    rc = RateCard.query.get_or_404(qid)
    db.session.delete(rc)
    db.session.commit()
    flash("Container quote rejected and removed.", "info")
    return redirect(url_for("admin.container_quotes_admin"))

@admin_bp.route("/container-quotes")
@admin_required
def container_quotes_admin():
    from app.models import RateCard
    pending  = RateCard.query.filter_by(is_active=False).order_by(RateCard.created_at.desc()).all()
    approved = RateCard.query.filter_by(is_active=True).order_by(RateCard.created_at.desc()).all()
    return render_template("admin/container_quotes.html",
        title="Container quotes", pending=pending, approved=approved)


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN PURCHASE ORDER ACTIONS
# ═══════════════════════════════════════════════════════════════════════════


@admin_bp.route("/purchase-orders")
@admin_required
def purchase_orders():
    pos_raw = PurchaseOrder.query.order_by(PurchaseOrder.created_at.desc()).all()

    def po_to_card(po):
        b = po.booking
        supplier = b.supplier if b else None
        shipper_price = po.gross_amount or (b.quoted_value if b else 0) or 0
        supplier_rate = po.net_payable or (b.supplier_payout if b else 0) or 0
        platform_fee = po.platform_fee if po.platform_fee is not None else max(shipper_price - supplier_rate, 0)
        status_map = {
            "Invoice Pending": "Awaiting invoice",
            "Invoice Received": "Invoice Received",
            "Approved": "Approved for payment",
            "Paid": "Paid",
        }
        payment_status = status_map.get(po.status, po.status or "Awaiting invoice")
        return {
            "id": po.id,
            "poNumber": po.po_number,
            "supplierName": supplier.company_name if supplier else "-",
            "ref": b.ref if b else "-",
            "route": b.route if b else "-",
            "commodity": b.commodity if b else "-",
            "supplierRate": supplier_rate,
            "platformFee": platform_fee,
            "agreedRate": shipper_price,
            "netPayable": supplier_rate,
            "status": po.status,
            "paymentStatus": payment_status,
            "invoiceFilename": po.invoice_filename,
            "invoiceVerified": po.status in ("Approved", "Paid"),
            "invoiceVerifiedBy": "Finance" if po.approved_at else None,
            "invoiceVerifiedAt": po.approved_at.strftime("%d %b %Y %H:%M") if po.approved_at else None,
            "paidAt": po.paid_at.strftime("%d %b %Y %H:%M") if po.paid_at else None,
            "issuedAt": po.created_at.strftime("%d %b %Y") if po.created_at else "-",
        }

    pos = [po_to_card(po) for po in pos_raw]
    pending_verification = [po for po in pos if po["status"] == "Invoice Received"]
    return render_template("admin/purchase_orders.html", title="Purchase orders", pos=pos, pending_verification=pending_verification)

@admin_bp.route("/purchase-orders/<int:po_id>/approve", methods=["POST"])
@admin_required
def approve_po(po_id):
    po = PurchaseOrder.query.get_or_404(po_id)
    ok, reason = can_approve_po(po)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("admin.purchase_orders"))
    po.status      = "Approved"
    po.approved_at = datetime.utcnow()
    log_finance_event(po.booking, "Supplier Invoice Approved",
        f"Admin reviewed the supplier invoice and complete evidence package for {po.po_number}. Payout is approved and may now be released.",
        current_user.full_name)
    db.session.commit()
    push_notification(po.booking.supplier.user_id,
        f"Invoice approved - {po.po_number}",
        f"Your invoice for {po.po_number} has been approved. Payment will be released within 48 hours.",
        type="success")
    flash(f"{po.po_number} approved. Supplier notified.", "success")
    log_action(current_user.id, "PO_APPROVED", "PurchaseOrder", po.po_number, "")
    return redirect(url_for("admin.purchase_orders"))

@admin_bp.route("/purchase-orders/<int:po_id>/reject", methods=["POST"])
@admin_required
def reject_po(po_id):
    po = PurchaseOrder.query.get_or_404(po_id)
    reason = request.form.get("reason","")
    po.status = "Invoice Pending"
    po.invoice_filename = None
    po.invoice_uploaded_at = None
    log_finance_event(po.booking, "Supplier Invoice Rejected",
        f"Finance rejected {po.po_number}. Supplier must re-upload. Reason: {reason}",
        current_user.full_name)
    db.session.commit()
    push_notification(po.booking.supplier.user_id,
        f"Invoice rejected - {po.po_number}",
        f"Your invoice was rejected. Reason: {reason}. Please re-upload.",
        type="error")
    flash(f"Invoice rejected. Supplier notified to re-upload.", "info")
    return redirect(url_for("admin.purchase_orders"))

@admin_bp.route("/purchase-orders/<int:po_id>/release", methods=["POST"])
@admin_required
def release_payout(po_id):
    po = PurchaseOrder.query.get_or_404(po_id)
    ok, reason = can_release_payout(po)
    if not ok:
        flash(reason, "error")
        return redirect(url_for("admin.purchase_orders"))
    supplier = po.booking.supplier
    if not supplier or not supplier.bank_name or not supplier.bank_account or not supplier.account_holder:
        flash("Supplier banking details are incomplete. Payment cannot be released.", "error")
        return redirect(url_for("admin.purchase_orders"))

    payout = Payout(
        supplier_id=supplier.id,
        amount=po.net_payable or 0,
        bookings_count=1,
        bank_summary=f"{supplier.bank_name} ···{supplier.bank_account[-4:]}",
        paid_by_id=current_user.id,
    )
    payout.generate_ref()
    db.session.add(payout)
    po.status  = "Paid"
    po.paid_at = datetime.utcnow()
    log_finance_event(po.booking, "Supplier Paid",
        f"Admin released payout {payout.payout_ref} for {po.po_number}. Net payout: R{po.net_payable:,.2f}.",
        current_user.full_name)
    db.session.commit()
    push_notification(po.booking.supplier.user_id,
        f"Payment released - {po.po_number}",
        f"R{po.net_payable:,.2f} has been released to your registered bank account for {po.po_number}. Payment reference: {payout.payout_ref}.",
        type="success")
    flash(f"Payment of R{po.net_payable:,.2f} released for {po.po_number}. Reference: {payout.payout_ref}.", "success")
    log_action(current_user.id, "PAYOUT_RELEASED", "PurchaseOrder", po.po_number, f"R{po.net_payable}")
    return redirect(url_for("admin.purchase_orders"))


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN SUPPLIER APPROVALS - document verify/request re-upload/revoke
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route("/approvals/<int:app_doc_id>/verify", methods=["POST"])
@admin_required
def verify_approval_doc(app_doc_id):
    from app.models import ComplianceDocument
    doc = ComplianceDocument.query.get_or_404(app_doc_id)
    doc.status      = "Verified"
    doc.verified_at = datetime.utcnow()
    db.session.commit()
    flash(f"{doc.name} verified.", "success")
    return redirect(url_for("admin.documents"))

@admin_bp.route("/approvals/<int:app_doc_id>/reupload", methods=["POST"])
@admin_required
def reupload_approval_doc(app_doc_id):
    from app.models import ComplianceDocument
    doc = ComplianceDocument.query.get_or_404(app_doc_id)
    doc.status = "Awaiting re-upload"
    db.session.commit()
    push_notification(doc.supplier.user_id,
        f"Document re-upload requested - {doc.name}",
        "Please upload a new version of this document to complete your approval.",
        type="warning")
    flash(f"Re-upload requested for {doc.name}.", "info")
    return redirect(url_for("admin.documents"))

@admin_bp.route("/approvals/<int:sid>/revoke", methods=["POST"])
@admin_required
def revoke_supplier(sid):
    s = SupplierProfile.query.get_or_404(sid)
    s.status = "Suspended"
    db.session.commit()
    push_notification(s.user_id, "Account suspended",
        "Your FreightFlow supplier account has been suspended. Contact support@movement.com.",
        type="error")
    flash(f"{s.company_name} suspended.", "info")
    log_action(current_user.id, "SUPPLIER_REVOKED", "SupplierProfile", str(sid), "")
    return redirect(url_for("admin.documents"))


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN REPORT / SUPPLIER INSIGHT ACTIONS
# ═══════════════════════════════════════════════════════════════════════════

@admin_bp.route("/reports/<ref>/resolve", methods=["POST"])
@admin_required
def resolve_report(ref):
    c = Complaint.query.filter_by(ref=ref).first_or_404()
    c.status      = "Resolved"
    c.resolved_at = datetime.utcnow()
    db.session.commit()
    push_notification(c.shipper.user_id, f"Complaint resolved - {ref}",
        "Your complaint has been marked resolved by admin.", type="success")
    flash(f"Complaint {ref} resolved.", "success")
    return redirect(url_for("admin.complaint_detail", ref=ref))

@admin_bp.route("/reports/<ref>/escalate", methods=["POST"])
@admin_required
def escalate_report(ref):
    c = Complaint.query.filter_by(ref=ref).first_or_404()
    c.priority = "Critical"
    db.session.commit()
    flash(f"Complaint {ref} escalated to Critical.", "warning")
    return redirect(url_for("admin.complaint_detail", ref=ref))

@admin_bp.route("/reports/<ref>/reply", methods=["POST"])
@admin_required
def reply_report(ref):
    from app.models import ComplaintMessage
    c = Complaint.query.filter_by(ref=ref).first_or_404()
    body = request.form.get("body","").strip()
    if body:
        msg = ComplaintMessage(complaint_id=c.id,
            sender_id=current_user.id, body=body)
        db.session.add(msg)
        db.session.commit()
        push_notification(c.shipper.user_id, f"Admin replied - {ref}", body[:120], type="info")
        flash("Reply sent.", "success")
    return redirect(url_for("admin.complaint_detail", ref=ref))

@admin_bp.route("/supplier-insights/<int:sid>/flag", methods=["POST"])
@admin_required
def flag_supplier(sid):
    s = SupplierProfile.query.get_or_404(sid)
    s.risk_flag = request.form.get("reason","Flagged by admin")
    db.session.commit()
    flash(f"{s.company_name} flagged.", "warning")
    return redirect(url_for("admin.supplier_risk"))

@admin_bp.route("/supplier-insights/<int:sid>/note", methods=["POST"])
@admin_required
def save_supplier_note(sid):
    s = SupplierProfile.query.get_or_404(sid)
    s.admin_notes = request.form.get("note","")
    db.session.commit()
    flash("Note saved.", "success")
    return redirect(url_for("admin.supplier_risk"))


# ─────────────────────────────────────────────────────────────────────────────
# Button-level repair endpoints (demo-safe actions with real routes)
# ─────────────────────────────────────────────────────────────────────────────
@admin_bp.route("/reports/download/<report_id>/<fmt>")
@admin_required
def download_report(report_id, fmt):
    fmt = (fmt or "csv").lower()
    if fmt not in {"csv", "xlsx", "pdf"}:
        fmt = "csv"
    payload = io.StringIO()
    writer = csv.writer(payload)
    writer.writerow(["Report", "Format", "Generated", "Total bookings", "Platform fees"])
    writer.writerow([report_id, fmt.upper(), datetime.utcnow().strftime("%Y-%m-%d %H:%M"), Booking.query.count(), db.session.query(db.func.sum(Booking.platform_fee)).scalar() or 0])
    data = payload.getvalue().encode("utf-8")
    from flask import send_file
    return send_file(io.BytesIO(data), mimetype="text/csv", as_attachment=True, download_name=f"{report_id}.{ 'csv' if fmt in {'csv','xlsx','pdf'} else fmt}")

@admin_bp.route("/purchase-orders/<int:po_id>/invoice/download")
@admin_required
def download_po_invoice(po_id):
    po = PurchaseOrder.query.get_or_404(po_id)
    filename = po.invoice_filename
    if filename:
        path = os.path.abspath(os.path.join("app", "static", "supplier_invoices", filename))
        if os.path.exists(path):
            return send_file(path, as_attachment=False, download_name=filename)
    content = (
        "FreightFlow Nexus Supplier Invoice Record\n"
        f"PO: {po.po_number}\n"
        f"Booking: {po.booking.ref if po.booking else '-'}\n"
        f"Supplier: {po.booking.supplier.company_name if po.booking and po.booking.supplier else '-'}\n"
        f"Status: {po.status}\n"
        f"Invoice file: {filename or 'No invoice file uploaded'}\n"
        f"Net payable: R{(po.net_payable or 0):,.2f}\n"
    )
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/plain",
                     as_attachment=False, download_name=f"{po.po_number}-invoice-record.txt")

@admin_bp.route("/drivers")
@admin_required
def drivers_admin():
    drivers = Driver.query.order_by(Driver.name).all()
    suppliers = SupplierProfile.query.all()
    rows = []
    for d in drivers:
        rows.append({
            "id": d.id,
            "name": d.name,
            "supplierId": d.supplier_id,
            "supplierName": d.supplier.company_name if d.supplier else "-",
            "vehicleReg": d.phone or "-",
            "licenseType": d.license_code or "EC",
            "licenseExpiry": d.license_expiry.strftime("%d %b %Y") if d.license_expiry else "-",
            "totalDeliveries": d.total_trips or 0,
            "onTimeRate": 95,
            "rating": d.rating or 0,
            "status": d.status or "Active",
        })
    return render_template("admin/drivers.html", title="Drivers", drivers=rows, suppliers=suppliers)

@admin_bp.route("/drivers/<int:driver_id>/review")
@admin_required
def driver_review(driver_id):
    d = Driver.query.get_or_404(driver_id)
    flash(f"Driver review opened for {d.name}. Licence: {d.license_code or '-'}, status: {d.status or '-'}.", "info")
    return redirect(url_for("admin.drivers_admin"))

@admin_bp.route("/drivers/<int:driver_id>/flag", methods=["POST"])
@admin_required
def driver_flag(driver_id):
    d = Driver.query.get_or_404(driver_id)
    d.status = "Inactive"
    db.session.commit()
    flash(f"{d.name} flagged and set to Inactive.", "warning")
    return redirect(url_for("admin.drivers_admin"))

@admin_bp.route("/approvals/document/<int:app_doc_id>/download")
@admin_required
def download_approval_doc(app_doc_id):
    doc = ComplianceDocument.query.get_or_404(app_doc_id)
    filename = doc.filename
    if filename:
        path = os.path.abspath(os.path.join("app", "static", "supplier_documents", filename))
        if os.path.exists(path):
            return send_file(path, as_attachment=False, download_name=filename)
    content = f"FreightFlow Nexus compliance document\nDocument: {doc.name}\nSupplier ID: {doc.supplier_id}\nStatus: {doc.status}\nFilename: {filename or 'Not uploaded'}\n"
    return send_file(io.BytesIO(content.encode("utf-8")), mimetype="text/plain", as_attachment=False, download_name=f"document-{app_doc_id}.txt")

@admin_bp.route("/supplier-reports")
@admin_required
def supplier_reports():
    complaints = Complaint.query.order_by(Complaint.created_at.desc()).limit(100).all()
    reports = []
    for c in complaints:
        reports.append({
            "ref": c.ref,
            "shipper": c.shipper.company_name if c.shipper and c.shipper.company_name else (c.shipper.user.full_name if c.shipper and c.shipper.user else "-"),
            "supplier": c.supplier.company_name if c.supplier else "-",
            "description": c.description or "-",
            "createdAt": c.created_at.strftime("%d %b %Y") if c.created_at else "-",
            "status": c.status,
            "disputeAmount": c.dispute_amount,
        })
    return render_template("admin/supplier_reports.html", title="Supplier reports", reports=reports)


@admin_bp.route("/purchase-orders/<int:po_id>/invoice")
@admin_required
def download_supplier_invoice(po_id):
    po = PurchaseOrder.query.get_or_404(po_id)
    if not po.invoice_filename:
        flash("No supplier invoice has been submitted for this purchase order.", "error")
        return redirect(url_for("admin.purchase_orders"))
    path = os.path.abspath(os.path.join("app", "static", "supplier_invoices", po.invoice_filename))
    if not os.path.exists(path):
        flash("The supplier invoice file could not be found.", "error")
        return redirect(url_for("admin.purchase_orders"))
    return send_file(path, as_attachment=False, download_name=po.invoice_filename)


@admin_bp.route("/purchase-orders/<int:po_id>/evidence-pack-pdf")
@admin_required
def download_evidence_pack_pdf(po_id):
    from app.services.evidence_pack import combined_service_pack_pdf
    po = PurchaseOrder.query.get_or_404(po_id)
    return send_file(
        io.BytesIO(combined_service_pack_pdf(po.booking, po)),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{po.booking.ref}-admin-review-pack.pdf",
    )


@admin_bp.route("/purchase-orders/<int:po_id>/evidence-pack")
@admin_required
def download_evidence_pack(po_id):
    from app.services.evidence_pack import build_service_pack
    po=PurchaseOrder.query.get_or_404(po_id)
    return send_file(build_service_pack(po.booking,po),mimetype="application/zip",as_attachment=True,download_name=f"{po.booking.ref}-finance-evidence-pack.zip")
