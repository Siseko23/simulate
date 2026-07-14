# FreightFlow Nexus — Booking Flow Guard Fixes

This build adds central business-flow guardrails so users cannot skip the core logistics lifecycle.

## Enforced lifecycle

1. Booking created as `Pending Quotes`
2. Supplier submits quote
3. Booking becomes `Quotes Received`
4. Shipper selects quote
5. Booking becomes `Awaiting Payment`
6. Shipper pays invoice
7. Booking becomes `Pending Supplier Acceptance`
8. Supplier accepts booking
9. Booking becomes `Confirmed`
10. Supplier dispatches driver + vehicle
11. Booking becomes `Driver Assigned`
12. Collection / transit / delivery statuses must follow order

## Important rule

The admin can no longer confirm or operationally move a booking on behalf of the supplier. Supplier acceptance is mandatory after payment.

## Fixed broken flows

- Supplier cannot dispatch before accepting a paid booking.
- Supplier cannot accept before shipper payment.
- Supplier acceptance now sets `Confirmed` only; driver assignment happens separately in dispatch.
- Supplier cannot jump from early statuses directly to `Delivered`.
- Driver cannot jump directly to `Delivered`.
- Admin cannot force operational statuses such as `Confirmed`, `Driver Assigned`, `In Transit`, or `Delivered`.
- Shipper cannot select a quote after payment/closure.
- Shipper cannot accept a quote from another booking.
- Reallocation is blocked after supplier acceptance, dispatch, transit, delivery, cancellation, or closure.
- Reallocation cannot use a quote from another booking.
- Waybill is locked until supplier acceptance.
- POD token is locked until dispatch and driver assignment.
- GIT insurance no longer auto-generates POD tokens too early.
- Public POD scan cannot mark a booking Delivered unless it is already in transit/approaching destination.
- Admin cannot approve a supplier PO until the supplier invoice has actually been uploaded.

## Audit checks passed

15/15 flow-abuse checks passed:

- Dispatch blocked before supplier acceptance
- Quote submission flow works
- Duplicate/late quote submission blocked
- Waybill blocked before supplier acceptance
- Quote selection moves booking to Awaiting Payment
- Invoice created unpaid
- Supplier accept blocked before payment
- Payment moves booking to Pending Supplier Acceptance
- Supplier accept moves booking to Confirmed only
- Dispatch after acceptance moves booking to Driver Assigned
- Supplier direct delivery jump blocked
- Driver direct delivery jump blocked
- Admin force Delivered blocked
- Admin PO approval blocked without supplier invoice

Smoke test: public, admin, shipper, supplier, and driver dashboards returned no server errors.
