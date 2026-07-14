# Supplier → Shipper Handoff Fix Audit — 2026-06-28

## User-reported issue
After the supplier accepts a booking, the shipper side did not clearly reflect the status change. Supplier dispatch also needed clear driver/vehicle selection, and shipper booking details needed to expose the waybill and assigned driver.

## Fixes applied

### 1. Shipper-side status visibility after supplier acceptance
- Added a shipper-facing `displayStatus` in `app/services/v19_adapter.py`.
- `Pending Dispatch` now displays as `Accepted by Supplier` to the shipper.
- Shipper booking list timeline now treats `Pending Dispatch` as a confirmed/accepted booking step.
- Shipper booking detail status panel now treats `Pending Dispatch` as supplier acceptance, not as an unconfirmed booking.

### 2. Supplier dispatch driver/vehicle selection
- Improved Supplier Dispatch page to show available drivers and vehicles clearly.
- Driver options now display license code and phone.
- Vehicle options now display vehicle type, registration number, payload tonnage, and CBM.
- Added empty-state messages when no available driver or vehicle exists.
- Dispatch route now separates pending dispatch jobs from active dispatched jobs.

### 3. Shipper booking detail: waybill + assigned driver
- Shipper booking detail now safely handles cases where the supplier accepted but no driver is assigned yet.
- Once a driver is assigned, the page shows driver name, phone, supplier, and vehicle registration.
- Waybill view/print remains available after supplier acceptance according to the agreed workflow.

## Targeted test performed
Using the local Flask test client and seeded database:

1. Prepared a paid booking in `Pending Supplier Acceptance`.
2. Logged in as supplier.
3. Accepted the booking.
4. Confirmed `/supplier/dispatch` showed selectable driver and vehicle radio inputs.
5. Assigned driver + vehicle.
6. Logged in as shipper.
7. Confirmed `/shipper/bookings` reflected the updated state.
8. Confirmed `/shipper/bookings/<ref>` displayed waybill access and assigned driver details.
9. Confirmed `/shipper/booking/<ref>/waybill` opened successfully.

## Result
Targeted workflow passed.

## Note
The database file was restored after testing, so the shipped demo database remains clean.
