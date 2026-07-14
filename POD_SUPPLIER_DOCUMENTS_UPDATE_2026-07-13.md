# POD Supplier Documents Update — 13 July 2026

Implemented the supplier-side proof-of-delivery and invoice evidence workflow.

## Changes
- Replaced the broken **Doc Waybill** button with a working **Documents** button.
- Added a supplier shipment document hub.
- Added working supplier waybill viewing.
- Added supplier POD downloads for files uploaded by the driver.
- Added a one-click Proof of Service Pack ZIP download.
- Added supplier notification when delivery and POD capture are complete.
- Linked purchase order, waybill and POD evidence to invoice submission.
- Changed the invoice action language from **Upload invoice** to **Submit invoice**.
- Kept compatibility with the existing SQLite database; no migration is required.
