# Context/logic fix audit — FFN v21

Source: `freightflow_nexus_v21_targeted_button_wiring_fixed.zip`
Output: `freightflow_nexus_v21_context_logic_fixed.zip`

## Issues patched

1. Supplier → Invoices (`/supplier/invoices`)
   - Added `completed_bookings` context expected by the template.
   - Added `platform_fee_pct` context from `PlatformSettings`.
   - Added payout-status mapping from PO/invoice state.

2. Supplier → Live Tracking (`/supplier/tracking`)
   - Added `drivers` context using v19 driver adapter.
   - Added `active_count` context.
   - Added `google_maps_key` context.
   - Added active-booking mapping per driver.

3. Supplier → Insights (`/supplier/insights`)
   - Added `monthly` chart data.
   - Added `score_hist` data.
   - Added `my_quotes` data.
   - Ensured `trajectory` is always available for Chart.js.

4. Shipper → Health Score (`/shipper/health-score`)
   - Added `avg_cost_per_km` to `compute_health_score()`.
   - Added `on_time_rate` to `compute_health_score()`.
   - Added `spend` trend data for Chart.js.
   - Added safe defaults for empty booking histories.

5. Admin → Audit Log (`/admin/audit-log`)
   - Replaced incorrect `admin/reports.html` rendering with a dedicated `admin/audit_log.html` template.
   - New template only expects `logs`, avoiding finance-report context errors.

6. Supplier status update
   - Confirmed latest source already no longer has the permanent early return/dead-code lock.

7. Supplier compliance upload links
   - Ensured compliance upload buttons route to `supplier.documents`.

## Validation performed in this environment

- Python syntax compilation passed for changed Python files:
  - `app/routes/supplier.py`
  - `app/routes/admin.py`
  - `app/routes/shipper.py`
  - `app/services/ai_engine.py`
- Template context defects were patched by matching route outputs to template expectations.

## Note

This execution environment does not currently have Flask installed, so full runtime route requests could not be executed here. The patched files compile successfully and directly address the reported UndefinedError/context bugs.
