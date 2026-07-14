# FreightFlow Nexus v21 — Functional Audit Report

Date: 2026-06-25
Build: `freightflow_nexus_v21_navigation_audited.zip`

## Fixes applied

### 1. View Booking Details
- Confirmed `/shipper/bookings/<ref>` works for shipper-owned bookings.
- Fixed the booking detail waybill action from placeholder `#` to a real internal route.
- Confirmed legacy detail route `/shipper/booking/<ref>` redirects correctly to the canonical detail page.

### 2. Rebook flow
- Changed rebook from direct booking creation to safe prefill flow.
- `/shipper/bookings/<ref>/reorder` now redirects to `/shipper/bookings/new` with copied shipment fields.
- Rebook no longer copies supplier, driver, quote, payment, invoice, POD, or booking status.
- Legacy `/reorder/confirm` endpoint no longer creates a booking directly; it redirects to the safe prefill flow.

### 3. Refresh / new tab behaviour
- Removed internal `target="_blank"` usage from templates.
- Replaced placeholder/new-tab waybill actions with same-tab internal navigation.
- No internal core page tested contains `target="_blank"` after patch.

### 4. Supplier flow hardening
- Supplier cannot manually mark bookings Collected/In Transit/Delivered from the supplier portal.
- Supplier can still accept paid bookings and dispatch driver/vehicle.
- Dispatch now validates that selected driver and vehicle belong to that supplier.
- Dispatch now blocks unavailable drivers/vehicles.
- Supplier waybill action now points to a real guarded waybill route.

### 5. Driver flow hardening
- Driver cannot mark Delivered unless POD has been signed/scanned.
- Driver GPS updates now require driver role, not just any logged-in user.
- Driver GPS update can only update bookings assigned to that driver.
- GPS update is blocked for inactive/non-live booking statuses.

## Functional audit results

### Page / navigation audit
- Public routes tested: landing, login/register aliases, tracking, invalid tracking.
- Shipper routes tested: dashboard, bookings list, booking detail, rebook, new shipment, analytics, invoices, address book, notifications, profile, legacy shipment/quotes/payments/detail aliases.
- Supplier routes tested: dashboard, bookings, quote requests, dispatch, fleet, drivers, availability, performance, documents, rates, purchase orders, tracking, container quotes, compliance, insights, invoices, reports.
- Driver routes tested: dashboard, assigned booking detail, profile, chat.
- Admin routes tested: dashboard, bookings, suppliers, shippers, users, marketplace, supplier risk, executive reports, audit log, documents, payouts, settings, container quotes, purchase orders.

Result: **96/96 navigation checks passed**.

### Abuse-flow audit
- Supplier direct status jump to Delivered blocked.
- Dispatch with invalid driver/vehicle blocked.
- Driver direct Delivered without POD blocked.
- Driver GPS update for own active booking accepted.
- Driver GPS update for another booking rejected.

Result: **7/7 abuse-flow checks passed**.

## Remaining recommended improvements

These are not hard failures, but they should be considered before a real production launch:

1. Add CSRF protection to all POST forms.
2. Add database migrations for new fields instead of relying on SQLite demo DB compatibility.
3. Replace demo payment with a real payment gateway sandbox.
4. Add file upload storage validation for supplier invoices and POD attachments.
5. Add automated tests into the repository so future patches do not re-break core flows.
6. Add formal role-permission tests for every route.
7. Add error pages for 403/404/500 with user-friendly messaging.
