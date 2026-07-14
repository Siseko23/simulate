# FreightFlow Nexus — User-first UX redesign

Implemented a task-first product redesign based on how real platform users think:

## Shipper
- Dashboard now starts with active shipments and next action, not graphs.
- Booking detail is structured around status timeline, shipment details, supplier, driver, documents, waybill and POD.
- Waybill/label preview is visual instead of hidden behind plain links.

## Supplier
- Dispatch screen now starts with jobs needing driver/vehicle assignment.
- Available drivers and vehicles are shown as operational cards.
- Assignment remains backed by the existing `/supplier/dispatch/<ref>/assign` route.

## Driver
- Driver dashboard now behaves like a mobile job card: navigate, scan collection, deliver/upload POD.
- Analytics are secondary to the next task.

## Admin
- Admin dashboard now prioritises exceptions and operational monitoring.
- Recent bookings, SLA watch, missing POD and payout queue are surfaced before vanity metrics.

## Homepage
- Rebuilt around the actual shipment workflow:
  shipment → quotes → label → PO → dispatch → QR scan → POD.
- Added a visual shipment widget, quote preview and label preview.

## Checks run
- App import check: passed.
- `/`: 200.
- `/auth/login`: 200.
- Shipper dashboard: 200.
- Shipper booking detail: 200.
- Supplier dispatch: 200.
- Driver dashboard: 200.
- Admin dashboard: 200.
