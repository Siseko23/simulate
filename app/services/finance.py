"""Finance guardrails for FreightFlow's marketplace payment model.

Shippers pay FreightFlow first. Funds are treated as platform-held escrow.
Suppliers are only paid after delivery, POD, supplier invoice upload,
and finance verification.
"""
from datetime import datetime
from typing import Tuple

from app.models import db, PurchaseOrder, BookingStatusEvent


PO_INVOICE_PENDING = "Invoice Pending"
PO_INVOICE_RECEIVED = "Invoice Received"
PO_APPROVED = "Approved"
PO_PAID = "Paid"


def ensure_supplier_purchase_order(booking) -> PurchaseOrder:
    """Create or refresh the supplier PO for the accepted booking quote."""
    po = booking.purchase_order
    gross = float(booking.quoted_value or 0)
    platform_fee = float(booking.platform_fee or 0)
    net = float(booking.supplier_payout or max(gross - platform_fee, 0))

    if po is None:
        po = PurchaseOrder(
            booking_id=booking.id,
            po_number=f"PO-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{booking.id}",
            gross_amount=gross,
            platform_fee=platform_fee,
            net_payable=net,
            status=PO_INVOICE_PENDING,
        )
        db.session.add(po)
    else:
        po.gross_amount = gross
        po.platform_fee = platform_fee
        po.net_payable = net
        if po.status not in (PO_INVOICE_RECEIVED, PO_APPROVED, PO_PAID):
            po.status = PO_INVOICE_PENDING
    return po


def can_supplier_upload_invoice(booking) -> Tuple[bool, str]:
    if booking.status != "Delivered":
        return False, "Supplier invoice upload is locked until the booking is delivered."
    if not booking.pod_signed:
        return False, "POD must be signed/scanned before supplier invoice upload."
    return True, ""


def can_approve_po(po) -> Tuple[bool, str]:
    booking = po.booking
    if po.status != PO_INVOICE_RECEIVED or not po.invoice_filename:
        return False, "Supplier invoice must be uploaded before finance can approve this PO."
    if not booking or booking.status != "Delivered":
        return False, "Finance can only approve supplier invoices for delivered bookings."
    if not booking.pod_signed:
        return False, "Finance cannot approve payout until POD is signed/scanned."
    return True, ""


def can_release_payout(po) -> Tuple[bool, str]:
    ok, reason = can_approve_po(po) if po.status == PO_INVOICE_RECEIVED else (True, "")
    if not ok:
        return False, reason
    if po.status != PO_APPROVED:
        return False, "PO must be verified/approved before payout can be released."
    if po.paid_at or po.status == PO_PAID:
        return False, "This supplier payout has already been released."
    booking = po.booking
    if not booking or booking.status != "Delivered":
        return False, "Supplier payout can only be released after delivery."
    if not booking.pod_signed:
        return False, "Supplier payout can only be released after POD is signed/scanned."
    if not po.invoice_filename:
        return False, "Supplier invoice is required before payout."
    return True, ""


def log_finance_event(booking, status: str, note: str, actor: str):
    db.session.add(BookingStatusEvent(
        booking_id=booking.id,
        status=status,
        note=note,
        actor=actor,
    ))
