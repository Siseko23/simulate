"""Order, QR and document lifecycle helpers for FreightFlow demo flow."""
from __future__ import annotations

from datetime import date, timedelta

from flask import url_for

from app.models import db, Booking, BookingStatusEvent, Invoice, PurchaseOrder, PODToken


def _absolute_url(endpoint: str, **values) -> str:
    try:
        return url_for(endpoint, _external=True, **values)
    except RuntimeError:
        return url_for(endpoint, **values)


def label_and_qr_links(booking: Booking) -> dict:
    """Return the operational links that connect label, collection and delivery."""
    return {
        "label_url": _absolute_url("shipper.shipment_label", ref=booking.ref),
        "collection_qr_url": _absolute_url("public.qr_scan", ref=booking.ref, event="collect"),
        "delivery_qr_url": _absolute_url("public.qr_scan", ref=booking.ref, event="deliver"),
    }


def ensure_shipper_order(booking: Booking, actor: str = "System") -> BookingStatusEvent | None:
    """Create a customer-facing order event immediately after quote acceptance.

    This is the operational order that tells the shipper to prepare the goods,
    print the label and use the QR links. It deliberately does not confirm that
    a supplier has accepted yet; supplier acceptance/dispatch remain later steps.
    """
    exists = BookingStatusEvent.query.filter_by(booking_id=booking.id, status="Order Generated").first()
    if exists:
        return None
    links = label_and_qr_links(booking)
    note = (
        f"Order generated instantly from accepted quote R{booking.quoted_value or 0:,.2f}. "
        f"Print label: {links['label_url']} | Collection QR: {links['collection_qr_url']} | "
        f"Delivery QR: {links['delivery_qr_url']}"
    )
    ev = BookingStatusEvent(booking_id=booking.id, status="Order Generated", note=note, actor=actor)
    db.session.add(ev)
    return ev


def apply_shipper_payment_terms(booking: Booking) -> Invoice:
    """Create/update the shipper invoice based on EFT or account credit terms."""
    shipper = booking.shipper
    amount = float(booking.quoted_value or 0)
    vat = round(amount * 0.15, 2)
    total = round(amount + vat, 2)
    inv = booking.invoice
    if not inv:
        inv = Invoice(booking_id=booking.id, amount=amount, vat_amount=vat, total_amount=total)
        inv.invoice_number = f"INV-{date.today().year}-{booking.id or 0:05d}"
        db.session.add(inv)
    inv.amount = amount
    inv.vat_amount = vat
    inv.total_amount = total

    available_credit = max(0, (shipper.credit_limit or 0) - (shipper.credit_used or 0)) if shipper else 0
    if shipper and available_credit >= total and shipper.credit_limit:
        inv.status = "Account Terms"
        inv.due_date = date.today() + timedelta(days=30)
        booking.status = "Pending Supplier Acceptance"
        booking.start_supplier_response_sla()
        shipper.credit_used = (shipper.credit_used or 0) + total
    else:
        inv.status = "Unpaid"
        inv.due_date = date.today() + timedelta(days=7)
        booking.status = "Awaiting Payment"
    return inv


def ensure_delivery_pod_token(booking: Booking) -> PODToken:
    import secrets
    if not booking.pod_token:
        tok = PODToken(booking_id=booking.id, token=secrets.token_urlsafe(32))
        db.session.add(tok)
        return tok
    return booking.pod_token


def mark_ready_for_supplier_invoice(booking: Booking, actor: str = "System") -> None:
    """After POD/doc capture, move supplier PO to invoice queue."""
    po = booking.purchase_order
    if po and po.status == "Invoice Pending":
        return
    if po:
        po.status = "Invoice Pending"
    db.session.add(BookingStatusEvent(
        booking_id=booking.id,
        status="Supplier Invoice Ready",
        note="Delivery/POD captured. Supplier may submit invoice and supporting documents for finance approval.",
        actor=actor,
    ))
