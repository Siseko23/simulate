# FreightFlow Nexus v3.0 - Driver PWA Integration

Implemented on top of `freightflow_nexus_v21_job_based_dispatch_fixed(1).zip` as the master source.

## Added
- Integrated Driver PWA inside the existing Flask app.
- New routes:
  - `/driver/app`
  - `/driver/app/job/<ref>`
  - `/driver/app/job/<ref>/collect`
  - `/driver/app/job/<ref>/transit`
  - `/driver/app/job/<ref>/deliver`
  - `/driver/app/job/<ref>/location`
- Installable PWA manifest and service worker.
- Phone-first driver UI for assigned jobs, job detail, navigation, collection QR simulation, live GPS share, delivery QR simulation, POD upload and supporting documents.
- Demo mode login shortcuts for shipper, supplier, driver and admin.
- Location access request flow:
  - Shipper requests live driver location.
  - Supplier approves or rejects.
  - GPS endpoint only exposes live position after approval.

## Preserved
- Quote selection flow.
- Supplier quote acceptance.
- Order/label/QR workflow.
- Job-based driver and vehicle dispatch.
- Vehicle eligibility and availability checks.
- POD and supplier invoice workflow.

## Notes
- The PWA stays inside the web app for demo stability.
- Background GPS is simulated through browser geolocation for the demo.
- A native app can be built later if production requires continuous background tracking.
