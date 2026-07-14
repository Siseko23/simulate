"""Central booking lifecycle guardrails.

These helpers stop routes from skipping the real logistics workflow:
quote -> payment -> supplier acceptance -> dispatch -> collection -> transit -> delivery.
"""
from datetime import datetime, timedelta
from typing import Tuple

SUPPLIER_SLA_HOURS = 12

TERMINAL_STATUSES = {"Delivered", "Completed", "Cancelled"}
QUOTE_SELECTION_STATUSES = {"Quotes Received"}
PAYMENT_STATUSES = {"Awaiting Payment"}
SUPPLIER_ACCEPTANCE_STATUS = "Pending Supplier Acceptance"
SUPPLIER_ACCEPTED_STATUSES = {"Pending Dispatch", "Confirmed"}
DISPATCHABLE_STATUSES = {"Pending Dispatch", "Confirmed"}
WAYBILL_READY_STATUSES = {"Pending Dispatch", "Confirmed", "Driver Assigned", "Collected", "In Transit", "Approaching Destination", "Delivered"}
POD_TOKEN_READY_STATUSES = {"Driver Assigned", "Collected", "In Transit", "Approaching Destination"}

STATUS_TRANSITIONS = {
    "Confirmed": {"Driver Assigned", "Cancelled"},
    "Pending Dispatch": {"Driver Assigned", "Cancelled"},
    "Driver Assigned": {"Collected", "Cancelled"},
    "Collected": {"In Transit"},
    "In Transit": {"Approaching Destination", "Delivered"},
    "Approaching Destination": {"Delivered"},
}

ADMIN_FORCE_ALLOWED = {
    "Pending Quotes", "Quotes Received", "Awaiting Payment", "Pending Supplier Acceptance",
    "Supplier SLA Expired", "Cancelled"
}


def _now():
    return datetime.utcnow()


def start_supplier_response_sla(booking):
    """Start/reset the 12-hour window after shipper payment or paid reallocation."""
    if hasattr(booking, "start_supplier_response_sla"):
        booking.start_supplier_response_sla(SUPPLIER_SLA_HOURS)
    else:
        booking.supplier_response_deadline = _now() + timedelta(hours=SUPPLIER_SLA_HOURS)
        booking.supplier_accepted_at = None
        booking.driver_assigned_at = None
        booking.supplier_sla_status = "Pending"
    return booking.supplier_response_deadline


def expire_supplier_response_if_needed(booking) -> bool:
    """Expire booking if selected supplier missed acceptance+driver assignment SLA."""
    deadline = getattr(booking, "supplier_response_deadline", None)
    assigned_at = getattr(booking, "driver_assigned_at", None)
    if (
        deadline
        and not assigned_at
        and _now() > deadline
        and booking.status in {"Pending Supplier Acceptance", "Pending Dispatch", "Confirmed"}
    ):
        booking.status = "Supplier SLA Expired"
        booking.supplier_sla_status = "Expired"
        return True
    return False


def supplier_sla_message(booking) -> str:
    hours_left = getattr(booking, "supplier_response_hours_left", None)
    if callable(hours_left):
        hours_left = hours_left()
    if hours_left is None:
        return ""
    if hours_left <= 0:
        return "The 12-hour supplier response window has expired."
    return f"Supplier must accept and assign a driver within {hours_left} hours."


def can_select_quote(booking, quote=None) -> Tuple[bool, str]:
    if booking.status not in QUOTE_SELECTION_STATUSES:
        return False, "Quotes can only be selected while the booking is in Quotes Received status."
    if booking.invoice and booking.invoice.status == "Paid":
        return False, "This booking has already been paid and cannot change quote."
    if booking.status in TERMINAL_STATUSES:
        return False, "Closed bookings cannot have quotes selected."
    if quote is not None:
        if quote.booking_id != booking.id:
            return False, "Quote does not belong to this booking."
        if quote.status not in ("Pending", "Submitted", "Quoted", None):
            return False, "This quote is no longer available for selection."
    return True, ""


def can_pay_booking(booking) -> Tuple[bool, str]:
    if booking.status != "Awaiting Payment":
        return False, "Payment is only allowed after a quote is selected and the booking is Awaiting Payment."
    if not booking.accepted_quote_id:
        return False, "Select a supplier quote before payment."
    if not booking.invoice:
        return False, "No invoice exists for this booking."
    if booking.invoice.status == "Paid":
        return False, "This invoice has already been paid."
    return True, ""


def supplier_can_accept(booking) -> Tuple[bool, str]:
    if expire_supplier_response_if_needed(booking):
        return False, "The 12-hour supplier acceptance/dispatch window has expired. The shipper must select another supplier or reassign the booking."
    if booking.status != SUPPLIER_ACCEPTANCE_STATUS:
        return False, "Supplier can only accept after shipper payment."
    if not booking.accepted_quote_id:
        return False, "No selected quote exists for this booking."
    if not booking.invoice or booking.invoice.status != "Paid":
        return False, "Supplier cannot accept until shipper payment is Paid."
    if not getattr(booking, "supplier_response_deadline", None):
        start_supplier_response_sla(booking)
    return True, ""


def can_dispatch(booking) -> Tuple[bool, str]:
    if expire_supplier_response_if_needed(booking):
        return False, "The 12-hour supplier acceptance/dispatch window has expired. Driver assignment is locked."
    if booking.status not in DISPATCHABLE_STATUSES:
        return False, "Dispatch is only allowed after the supplier accepts the paid booking."
    if not booking.invoice or booking.invoice.status != "Paid":
        return False, "Cannot dispatch before shipper payment is Paid."
    if not booking.supplier_id:
        return False, "Cannot dispatch until a supplier is assigned."
    if not getattr(booking, "supplier_accepted_at", None):
        return False, "Supplier must accept the booking before assigning a driver."
    return True, ""


def can_transition(booking, new_status: str) -> Tuple[bool, str]:
    allowed = STATUS_TRANSITIONS.get(booking.status, set())
    if new_status not in allowed:
        return False, f"Invalid status jump: {booking.status} -> {new_status}."
    return True, ""


def can_reallocate(booking) -> Tuple[bool, str]:
    if booking.status not in {"Quotes Received", "Pending Supplier Acceptance", "Supplier SLA Expired"}:
        return False, "Reallocation is only allowed before supplier acceptance/dispatch, or after a supplier SLA expiry."
    if booking.status in TERMINAL_STATUSES:
        return False, "Closed bookings cannot be reallocated."
    return True, ""


def can_view_waybill(booking) -> Tuple[bool, str]:
    if booking.status not in WAYBILL_READY_STATUSES:
        return False, "Waybill is locked until the supplier accepts the paid booking."
    return True, ""


def can_generate_pod_token(booking) -> Tuple[bool, str]:
    if booking.status not in POD_TOKEN_READY_STATUSES:
        return False, "POD token can only be generated after dispatch and before final delivery."
    if not booking.driver_id:
        return False, "Assign a driver before generating a POD token."
    return True, ""


def can_scan_pod(booking) -> Tuple[bool, str]:
    if booking.status not in {"In Transit", "Approaching Destination"}:
        return False, "POD delivery scan is only valid when the shipment is in transit or approaching destination."
    return True, ""


def can_submit_quote(booking) -> Tuple[bool, str]:
    if booking.status != "Pending Quotes":
        return False, "Quotes can only be submitted for bookings that are still Pending Quotes."
    return True, ""


def admin_can_force_status(new_status: str) -> Tuple[bool, str]:
    if new_status not in ADMIN_FORCE_ALLOWED:
        return False, "Admin cannot force operational statuses. Supplier/driver actions must move the booking after payment."
    return True, ""
