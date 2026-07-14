# Supplier 12-Hour Acceptance + Driver Assignment SLA Update

## Requirement
When a supplier is selected for a booking after shipper payment, the supplier must accept the booking and assign a driver/vehicle within 12 hours.

## Implemented Behaviour
- Payment to FreightFlow starts a 12-hour supplier SLA window.
- Booking moves to `Pending Supplier Acceptance`.
- Supplier acceptance moves booking to `Pending Dispatch`, not straight to a fully dispatched state.
- Supplier must assign driver + vehicle before the 12-hour deadline expires.
- Driver assignment completes the SLA and moves booking to `Driver Assigned`.
- If the deadline expires before driver assignment, booking moves to `Supplier SLA Expired`.
- Expired bookings cannot be accepted or dispatched by the supplier.
- Reallocation now supports `Supplier SLA Expired` so the shipper can select another supplier.

## Files Changed
- `app/models/__init__.py`
- `app/services/lifecycle.py`
- `app/routes/shipper.py`
- `app/routes/supplier.py`
- `app/services/v19_adapter.py`
- `app/templates/supplier/bookings.html`
- `app/templates/supplier/dispatch.html`
- `app/templates/supplier/dashboard.html`
- `app/__init__.py`
- `migrate_new_features.sql`

## Database Fields Added
- `bookings.supplier_response_deadline`
- `bookings.supplier_accepted_at`
- `bookings.driver_assigned_at`
- `bookings.supplier_sla_status`

## Targeted Test Result
Manual lifecycle function test passed:
- SLA deadline starts after paid booking.
- Supplier can accept before deadline.
- Supplier can dispatch after acceptance and before deadline.
- Dispatch is blocked after deadline.
- Expired booking status becomes `Supplier SLA Expired`.
