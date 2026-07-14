# Shipper Button Fix Audit — 2026-06-28

Scope requested by user:
- Shipper → Bookings → View details
- Shipper → Bookings → Reorder
- Shipper → Payments → View invoice

## Fixes applied

### 1. View details
Verified `/shipper/bookings/<ref>` returns the shipper booking detail page for every visible booking owned by the logged-in shipper.

### 2. Reorder
Changed reorder from a long redirect-with-query-string flow to a direct render of the New Shipment form.

Why: long address query strings can be truncated or look broken in browsers/proxies. The new route now renders the form directly and pre-fills the shipment fields without creating a booking.

Also fixed missing prefill names:
- `pieces`
- `quantity`
- `weightPerItem`
- `weight_per_item`
- `vehicleType`
- collection/delivery addresses and contacts

### 3. View invoice in Payments
Added a proper HTML invoice view route:
- `/shipper/invoices/<invoice_id>`
- `/shipper/payments/<invoice_id>/invoice`

Updated the Payments/Invoices list so “View invoice” opens the HTML invoice page instead of a raw text download response.

The invoice view includes:
- invoice number
- booking reference
- route
- status
- subtotal
- VAT
- total
- link back to booking details
- download/printable copy link

## Verification
Logged in as `shipper1@movement.com` and tested:

- Every visible `View details` link under `/shipper/bookings`: HTTP 200
- Every visible `Reorder` link under `/shipper/bookings`: HTTP 200, form rendered directly
- `/shipper/payments`: HTTP 200
- Every visible `View invoice` link under `/shipper/payments`: HTTP 200 HTML invoice page

## Important note
This fix specifically addresses the buttons the user reported as still broken. It does not claim a full new audit of every button across the entire application.
