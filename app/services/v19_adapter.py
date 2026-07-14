"""
v19 Template Adapter
Converts SQLAlchemy model instances into flat dicts that match
the variable shapes the v19 Jinja templates expect.
"""
from app.models import Booking, SupplierProfile
import os

# High-theft route corridors (from atypica.AI research)
HIGH_RISK_CORRIDORS = [
    ("johannesburg", "limpopo"), ("joburg", "limpopo"),
    ("gauteng", "limpopo"), ("pretoria", "limpopo"),
    ("johannesburg", "mpumalanga"), ("gauteng", "mpumalanga"),
    ("johannesburg", "north west"), ("gauteng", "north west"),
    ("durban", "johannesburg"), ("durban", "joburg"),
    ("cape town", "johannesburg"), ("cape town", "joburg"),
    ("johannesburg", "northern cape"), ("gauteng", "northern cape"),
]

def _route_risk(collection_city: str, delivery_city: str) -> dict:
    """Return risk flag and message for a route pair."""
    c = (collection_city or "").lower()
    d = (delivery_city or "").lower()
    for a, b in HIGH_RISK_CORRIDORS:
        if (a in c or a in d) and (b in c or b in d):
            return {
                "isHighRisk": True,
                "riskMessage": f"Warning This corridor ({collection_city} -> {delivery_city}) has elevated cargo theft risk. GIT insurance and telematics tracking strongly recommended.",
            }
    return {"isHighRisk": False, "riskMessage": ""}


def booking_to_v19(b: Booking) -> dict:
    """Convert a Booking ORM object to a v19-compatible dict."""
    # GIT insurance
    git = b.git_insurance
    git_data = {
        "hasGIT": bool(git),
        "gitPolicyRef":   git.policy_ref if git else "",
        "gitCoverAmount": git.cover_amount if git else 0,
        "gitPremium":     git.premium_amount if git else 0,
        "gitStatus":      git.status if git else "",
        "gitProvider":    git.provider if git else "",
    }

    # POD token / uploaded POD image
    pod = b.pod_token
    pod_photo_url = ""
    pod_dir = os.path.join("app", "static", "pod_photos")
    if b.ref and os.path.isdir(pod_dir):
        safe_ref = b.ref.replace("/", "-")
        for name in sorted(os.listdir(pod_dir), reverse=True):
            if name.startswith(f"{safe_ref}_") or name.startswith(f"pod_{safe_ref}"):
                pod_photo_url = f"/static/pod_photos/{name}"
                break
    pod_data = {
        "podToken":    pod.token if pod else "",
        "podScanned":  pod.scanned if pod else False,
        "podScannedAt": pod.scanned_at.strftime("%d %b %H:%M") if pod and pod.scanned_at else "",
        "podSigned": bool(getattr(b, "pod_signed", False)),
        "podSignedAt": b.pod_signed_at.strftime("%d %b %H:%M") if getattr(b, "pod_signed_at", None) else "",
        "podPhotoUrl": pod_photo_url,
    }

    # Supplier performance card
    sup = b.supplier
    sup_perf = {}
    if sup:
        on_time_rate = round(sup.on_time_jobs / sup.total_jobs * 100, 1) if sup.total_jobs else 95.0
        cancel_rate  = round(sup.cancelled_jobs / sup.total_jobs * 100, 1) if sup.total_jobs else 0.0
        sup_perf = {
            "supplierTotalJobs":  sup.total_jobs,
            "supplierOnTimeRate": on_time_rate,
            "supplierScore":      sup.score,
            "supplierCancelRate": cancel_rate,
            "supplierSince":      sup.approved_at.strftime("%b %Y") if sup.approved_at else "-",
        }

    # Route risk
    risk = _route_risk(b.collection_city or "", b.delivery_city or "")

    # Driver vetting
    drv = b.driver
    drv_vetting = {}
    if drv:
        drv_vetting = {
            "driverVettingStatus":         drv.vetting_status or "Pending",
            "driverCriminalClearanceDate": drv.criminal_clearance_date.strftime("%d %b %Y") if drv.criminal_clearance_date else "-",
            "driverCriminalStatus":        drv.criminal_clearance_status or "Pending",
            "driverPDPExpiry":             drv.pdp_expiry.strftime("%d %b %Y") if drv.pdp_expiry else "-",
            "driverLicenseExpiry":         drv.license_expiry.strftime("%d %b %Y") if drv.license_expiry else "-",
            "driverLicenseCode":           drv.license_code or "EC",
        }

    # User-facing status label. The database keeps detailed operational states,
    # but the shipper should see supplier acceptance immediately as a confirmed booking.
    display_status = b.status or ""
    if display_status == "Pending Dispatch":
        display_status = "Accepted by Supplier"
    elif display_status == "Driver Assigned":
        display_status = "Driver Assigned"

    return {
        "ref":         b.ref,
        "route":       b.route or "",
        "status":      b.status or "",
        "displayStatus": display_status,
        "value":       b.quoted_value or 0,
        "shipper":     b.shipper.user.full_name if b.shipper and b.shipper.user else "-",
        "supplier":    sup.company_name if sup else "-",
        "supplierId":  b.supplier_id,
        "commodity":   b.commodity or "",
        "pieces":      b.pieces or 0,
        "unitType":    "pallets",
        "collectionAddress": b.collection_address or "",
        "collectionCity":    b.collection_city or "",
        "deliveryAddress":   b.delivery_address or "",
        "deliveryCity":      b.delivery_city or "",
        "collectionContact": b.collection_contact or "",
        "collectionPhone":   b.collection_phone or "",
        "deliveryContact":   b.delivery_contact or "",
        "deliveryPhone":     b.delivery_phone or "",
        "vehicleType":       b.vehicle_type_req or "",
        "driverName":        drv.name if drv else "-",
        "driverPhone":       drv.phone if drv and drv.phone else "",
        "driverLicenseCode":  drv.license_code if drv and drv.license_code else "",
        "vehicleReg":        b.vehicle.reg_number if b.vehicle else "-",
        "collectedAt":       b.collected_at.strftime("%d %b %H:%M") if b.collected_at else "",
        "deliveredAt":       b.delivered_at.strftime("%d %b %H:%M") if b.delivered_at else "",
        "createdAt":         b.created_at.strftime("%d %b %Y") if b.created_at else "",
        "collectionDate":    str(b.collection_date) if b.collection_date else "",
        "distance_km":       b.distance_km or 0,
        "platformFee":       b.platform_fee or 0,
        "supplierPayout":    b.supplier_payout or 0,
        "riskLevel":         b.risk_level or "Low",
        "notes":             b.notes or "",
        "locationAccessStatus": getattr(b, "location_access_status", "Not Requested") or "Not Requested",
        "locationAccessRequested": bool(getattr(b, "location_access_requested", False)),
        "locationAccessReason": getattr(b, "location_access_reason", "") or "",
        "isFragile":         bool(b.is_fragile),
        "supplierResponseWindow": (
            "SLA completed" if getattr(b, "driver_assigned_at", None) else
            (f"{b.supplier_response_hours_left}h remaining" if getattr(b, "supplier_response_hours_left", None) is not None else "12h SLA")
        ),
        "destinationType":   b.destination_type or "Direct",
        "weightPerItem":     b.weight_per_item_kg or 0,
        "totalWeight":       b.total_weight_kg or 0,
        "waybillGenerated":  (b.status in ["Pending Dispatch", "Confirmed", "Driver Assigned", "Collected", "In Transit", "Approaching Destination", "Delivered"]),
        # rating
        "rating":            b.rating,
        "ratingComment":     b.rating_comment or "",
        # GIT insurance
        **git_data,
        # POD QR
        **pod_data,
        # Supplier performance card
        **sup_perf,
        # Route risk
        **risk,
        # Driver vetting card
        **drv_vetting,
        # service events the shipper has logged against this booking
        "ratingEvents": [
            {"type": e.status, "label": e.note or e.status,
             "time": e.created_at.strftime("%d %b %H:%M"),
             "impact": {"delay_1h": -2, "delay_3h": -5, "delay_over3h": -10,
                        "dc_miss": -8, "damage": -15}.get(e.status, -1)}
            for e in sorted(
                [ev for ev in (b.status_events or [])
                 if ev.status in ("delay_1h", "delay_3h", "delay_over3h", "dc_miss", "damage")],
                key=lambda ev: ev.created_at, reverse=True
            )[:5]
        ],
        "statusEvents": [
            {"status": e.status, "note": e.note or "", "time": e.created_at.strftime("%d %b %H:%M")}
            for e in (b.status_events or [])
        ],
    }


def driver_to_v19(d) -> dict:
    """Convert a Driver to a v19-compatible dict for driver-portal templates."""
    active_bk = d.bookings.filter(Booking.status.in_(
        ["Driver Assigned", "Collected", "In Transit"])).first()
    vehicle = active_bk.vehicle if active_bk and active_bk.vehicle else None
    return {
        "id":              d.id,
        "name":            d.name,
        "email":           d.user.email if d.user else "",
        "phone":           d.phone or "",
        "idNumber":        d.id_number or "",
        "licenseType":     d.license_code or "",
        "licenseNo":       d.id_number or "",
        "licenseExpiry":   d.license_expiry.strftime("%d %b %Y") if d.license_expiry else "-",
        "status":          d.status,
        "rating":          d.rating,
        "totalDeliveries": d.total_trips,
        "onTimeRate":      92,
        "supplierName":    d.supplier.company_name if d.supplier else "-",
        "vehicleType":     vehicle.vehicle_type if vehicle else "-",
        "vehicleReg":      vehicle.reg_number if vehicle else "-",
        # vetting
        "vettingStatus":          d.vetting_status or "Pending",
        "criminalClearanceDate":  d.criminal_clearance_date.strftime("%d %b %Y") if d.criminal_clearance_date else "-",
        "criminalStatus":         d.criminal_clearance_status or "Pending",
        "pdpExpiry":              d.pdp_expiry.strftime("%d %b %Y") if d.pdp_expiry else "-",
    }


def supplier_to_v19(s: SupplierProfile) -> dict:
    """Convert a SupplierProfile to a v19-compatible dict."""
    return {
        "id":             s.id,
        "name":           s.company_name,
        "baseCity":       s.base_city or "",
        "region":         s.operating_region or "",
        "status":         s.status,
        "score":          s.score,
        "totalJobs":      s.total_jobs,
        "onTimeRate":     round(s.on_time_jobs / s.total_jobs * 100, 1) if s.total_jobs else 95.0,
        "cancellationRate": round(s.cancelled_jobs / s.total_jobs * 100, 1) if s.total_jobs else 0.0,
        "acceptanceRate": s.acceptance_rate,
        "approvedAt":     s.approved_at.strftime("%d %b %Y") if s.approved_at else "-",
        "createdAt":      s.created_at.strftime("%d %b %Y") if s.created_at else "-",
    }


def quote_to_v19(q, rank=None) -> dict:
    """Convert a Quote + SupplierProfile to v19-compatible dict."""
    sup = q.supplier
    # Broker equivalent estimate: supplier amount + 15% broker markup
    broker_equiv = round(q.amount * 1.175, 2) if q.amount else 0
    saving = round(broker_equiv - q.amount, 2)
    return {
        "id":            q.id,
        "supplier":      sup.company_name if sup else "-",
        "supplierId":    q.supplier_id,
        "amount":        q.amount,
        "brokerEquiv":   broker_equiv,
        "savingVsBroker": saving,
        "transitDays":   q.transit_days or 1,
        "notes":         q.notes or "",
        "status":        q.status,
        "aiScore":       q.ai_score or 0,
        "rank":          q.rank or rank or 1,
        "supplierScore": sup.score if sup else 0,
        "onTimeRate":    round(sup.on_time_jobs / sup.total_jobs * 100, 1) if sup and sup.total_jobs else 95.0,
        "supplierTotalJobs": sup.total_jobs if sup else 0,
        "supplierSince": sup.approved_at.strftime("%b %Y") if sup and sup.approved_at else "-",
        "reasons":       _explain_rank(q),
    }


def _explain_rank(q) -> list:
    sup = q.supplier
    reasons = []
    if q.rank == 1:
        reasons.append("Lowest adjusted cost after AI scoring")
    if sup and sup.score >= 4.5:
        reasons.append(f"Excellent reliability: {sup.score}/5.0")
    elif sup and sup.score >= 4.0:
        reasons.append(f"Good reliability: {sup.score}/5.0")
    elif sup:
        reasons.append(f"Below-average reliability: {sup.score}/5.0")
    if sup:
        reasons.append(f"On-time delivery: {sup.on_time_rate}%")
    return reasons
