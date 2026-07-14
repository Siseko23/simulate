# Equipment & Automation UX Update — 2026-06-30

Implemented into the user-first UX build.

## Added
- FreightFlow red-based core brand tokens.
- Visual equipment/trailer cards inside the shipment creation flow.
- Kargo AI recommendation panel that updates when a customer selects equipment.
- Trailer illustrations for Curtainsider, Superlink, Flatdeck/Lowbed, Reefer and Skeletal Trailer.
- Clear use cases, payload, pallet/volume and protection indicators on equipment cards.
- Homepage equipment showcase so users understand trailer types before creating an account.
- Automation timeline showing quote selected → label generated → PO created → driver assigned → QR/POD flow.

## Why
Customers should not have to know logistics trailer names before booking. The UI now shows what each option is used for so users avoid choosing the wrong vehicle.

## Checked
- App imports successfully.
- Homepage loads.
- Login page loads.
- Shipper shipment page loads after registering a test shipper.
- Equipment cards appear and write to the hidden vehicleType field.
