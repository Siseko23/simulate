"""Dispatch eligibility helpers for supplier driver/vehicle assignment.

Keeps dispatch rules in one place so supplier UI and assignment validation
use the same logic: available driver + available vehicle + vehicle fits booking.
"""
from __future__ import annotations

from typing import Any

from app.models import Booking, Driver, Vehicle
from app.services.ai_engine import equipment_fit

ACTIVE_DRIVER_STATUSES = {"Active", "Available"}
ACTIVE_VEHICLE_STATUSES = {"Available"}
ACTIVE_BOOKING_STATUSES = {
    "Driver Assigned",
    "Collected",
    "In Transit",
    "Approaching Destination",
}


def _active_booking_query(model, supplier_id: int):
    return Booking.query.filter(
        Booking.supplier_id == supplier_id,
        Booking.status.in_(ACTIVE_BOOKING_STATUSES),
    )


def driver_is_available(driver: Driver) -> tuple[bool, str]:
    """Return whether a driver can be used for a new dispatch assignment."""
    if not driver:
        return False, "Driver not found."
    if driver.status not in ACTIVE_DRIVER_STATUSES:
        return False, f"Driver status is {driver.status or 'Unknown'}."
    if not driver.user_id:
        return False, "Driver has no portal access yet."
    # Drivers are not permanently locked to one truck. A supplier may assign
    # the same vetted driver to a different available vehicle per job/day.
    active = _active_booking_query(Booking, driver.supplier_id).filter(
        Booking.driver_id == driver.id
    ).first()
    if active:
        return False, f"Driver is already assigned to {active.ref}."
    return True, "Available"


def vehicle_is_available(vehicle: Vehicle) -> tuple[bool, str]:
    """Return whether a vehicle can be used for a new dispatch assignment."""
    if not vehicle:
        return False, "Vehicle not found."
    if vehicle.availability not in ACTIVE_VEHICLE_STATUSES:
        return False, f"Vehicle status is {vehicle.availability or 'Unknown'}."
    active = _active_booking_query(Booking, vehicle.supplier_id).filter(
        Booking.vehicle_id == vehicle.id
    ).first()
    if active:
        return False, f"Vehicle is already assigned to {active.ref}."
    return True, "Available"


def vehicle_fits_booking(booking: Booking, vehicle: Vehicle) -> tuple[bool, dict[str, Any]]:
    """Use Kargo equipment fit logic to decide if a vehicle is eligible."""
    fit = equipment_fit(booking, getattr(vehicle, "vehicle_type", None))
    score = float(fit.get("score") or 0)
    utilisation = fit.get("utilisation")

    # Hard block obvious overloads, but allow near-capacity jobs with a warning.
    overloaded = utilisation is not None and float(utilisation) > 110
    eligible = score >= 0.55 and not overloaded
    if overloaded:
        fit.setdefault("reasons", []).append("Vehicle is overloaded for this shipment.")
    return eligible, fit


def eligible_dispatch_data(booking: Booking, supplier) -> dict[str, Any]:
    """Build per-booking eligible drivers, vehicles and driver/vehicle pairs."""
    drivers = supplier.drivers.all()
    vehicles = supplier.vehicles.all()

    eligible_drivers = []
    blocked_drivers = []
    for d in drivers:
        ok, reason = driver_is_available(d)
        item = {"driver": d, "ok": ok, "reason": reason}
        (eligible_drivers if ok else blocked_drivers).append(item)

    eligible_vehicles = []
    blocked_vehicles = []
    for v in vehicles:
        available_ok, availability_reason = vehicle_is_available(v)
        fit_ok, fit = vehicle_fits_booking(booking, v)
        ok = available_ok and fit_ok
        reason = availability_reason if not available_ok else ("Eligible" if fit_ok else "; ".join(fit.get("reasons") or ["Vehicle does not fit this shipment."]))
        item = {"vehicle": v, "ok": ok, "reason": reason, "fit": fit}
        (eligible_vehicles if ok else blocked_vehicles).append(item)

    # Driver and truck are separate operational choices. Default driver→vehicle
    # pairings are only suggestions; dispatch can pair any available driver with
    # any available vehicle that fits the shipment profile.
    assignment_options = []
    for d_item in eligible_drivers:
        d = d_item["driver"]
        for v_item in eligible_vehicles:
            v = v_item["vehicle"]
            fit = v_item["fit"]
            assignment_options.append({
                "driver_id": d.id,
                "vehicle_id": v.id,
                "label": f"{d.name} - {v.vehicle_type} - {v.reg_number}",
                "driver": d,
                "vehicle": v,
                "fit": fit,
                "match_percent": round(float(fit.get("score") or 0) * 100),
            })

    # Best vehicle fit first, then by smallest vehicle that still fits.
    assignment_options.sort(
        key=lambda x: (x["match_percent"], -(x["vehicle"].payload_ton or 0)),
        reverse=True,
    )

    return {
        "eligible_drivers": eligible_drivers,
        "blocked_drivers": blocked_drivers,
        "eligible_vehicles": eligible_vehicles,
        "blocked_vehicles": blocked_vehicles,
        "assignment_options": assignment_options,
    }
