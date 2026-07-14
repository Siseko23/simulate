# Vehicle Image + Carousel Update — 2026-06-30

Implemented against the cinematic FreightFlow build.

## Changes

- Added a consistent vehicle image library under `app/static/img/vehicles/`.
- Added all vehicle types currently used by the platform:
  - Bakkie / LDV
  - Panel Van
  - 4 Ton Truck
  - 5 Ton Truck
  - 8 Ton Rigid
  - Curtainsider
  - Tautliner
  - Superlink
  - Refrigerated Truck
  - Flatbed
  - Lowbed
  - Skeletal Trailer
- Homepage vehicle section is now a horizontal slideshow/carousel of all vehicle types.
- Vehicle cards no longer show pricing on the dashboard/home vehicle section.
- New Shipment now shows an eligible vehicle slideshow next to the form, not inside the form.
- Eligible vehicle cards dim automatically when the current shipment is not a fit.
- Supplier Fleet and Supplier Dispatch now show vehicle images for each fleet/vehicle record.
- Pricing remains reserved for the quote flow, not the dashboard/equipment guidance sections.

## Files changed

- `app/templates/public/landing.html`
- `app/templates/landing.html`
- `app/templates/shipper/shipment.html`
- `app/templates/supplier/fleet.html`
- `app/templates/supplier/dispatch.html`
- `app/static/css/freightflow-design-system.css`
- `app/static/img/vehicles/*`

## Checks

- Python files compile.
- Jinja templates parse.
- Referenced vehicle image assets are included in the zip.
