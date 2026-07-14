# Driver-to-Vehicle Pairing Update

Implemented supplier-side driver-to-vehicle assignment.

## What changed

- Added `drivers.assigned_vehicle_id` to store each driver's default vehicle.
- Added supplier driver management controls to assign/reassign a driver to a vehicle.
- Driver creation now saves the selected vehicle assignment.
- Fleet options show when a vehicle is already assigned.
- Supplier dispatch now uses driver-vehicle pairs instead of free mixing drivers and vehicles.
- Dispatch only allows a pair when:
  - the driver is available,
  - the driver has portal access,
  - the driver has an assigned vehicle,
  - the assigned vehicle is available,
  - the assigned vehicle is eligible for the shipment according to Kargo equipment fit logic.
- Backend blocks invalid pairs even if someone bypasses the UI.
- Existing demo database was backfilled with default driver-vehicle pairings.

## Example

Supplier can now see assignment options like:

`Thabo - Bakkie / LDV - ND 123 456`

instead of selecting a driver and random vehicle separately.
