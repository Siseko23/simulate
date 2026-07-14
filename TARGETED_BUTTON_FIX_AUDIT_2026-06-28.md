# Targeted Button/Wiring Fix Audit — 2026-06-28

Source zip: `freightflow_nexus_v21_supplier_12hr_sla.zip`

## Fixes applied

### 1. Supplier `update_status` route no longer contains unreachable dead code
- File: `app/routes/supplier.py`
- The old route returned immediately before the status update logic.
- Replaced with guarded logic:
  - Missing status now returns a clear validation error.
  - Driver-only milestones (`Collected`, `In Transit`, `Approaching Destination`, `Delivered`) are explicitly blocked from supplier portal.
  - `Pending Dispatch` can be used only when it is a valid supplier acceptance step.
  - Valid lifecycle transitions now persist and create timeline events.

### 2. Compliance upload links corrected
- File: `app/templates/supplier/compliance.html`
- Changed both `Upload documents →` buttons from `supplier.performance` to `supplier.documents`.

### 3. Driver standalone demo scan buttons now POST to backend
- File: `app/templates/driver/app.html`
- Added `fetch('/api/driver/simulate-scan')` to `simulateScan(type)`.
- File: `app/routes/public.py`
- Added `POST /api/driver/simulate-scan`.
- The standalone driver UI now attempts to update booking status in the database for real deployments.
- It returns visible success/error feedback if the referenced booking exists or does not exist.

## Notes
- Supplier status controls still intentionally cannot fake live driver progress. That is a security/business-rule decision, not a broken button.
- Driver standalone demo uses static demo booking references. If those references do not exist in the deployed database, the UI now shows an error instead of pretending the DB updated.

## Static checks completed
- `supplier.performance` references removed from compliance upload CTAs.
- New API endpoint added under `api_bp`, mounted as `/api/driver/simulate-scan`.
- Python files compile syntactically in this environment.
