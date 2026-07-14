# FreightFlow Nexus — Systemic Frontend Design Fix

## What changed
- Added a central shared stylesheet: `app/static/css/freightflow-design-system.css`.
- Bridged existing template tokens (`--accent`, `--surface`, `--border`, `--radius`, etc.) to a consistent FreightFlow brand palette.
- Standardised core shared components globally: panels, cards, buttons, pills, form fields, tables, sidebar, topbar, auth cards and quote cards.
- Updated the main landing hero to use shared product classes instead of a one-off visual language.
- Added the shared stylesheet to standalone auth/public pages that do not inherit `base.html`.
- Replaced many repeated hardcoded template colours with design tokens so deeper pages inherit the same brand system.

## Why this matters
The previous frontend had strong copy but still felt stitched together because individual templates redefined colours, buttons and card styles. This fix makes the UI read as one FreightFlow product across landing, login, shipper, supplier, driver and admin areas.

## Still recommended later
- Gradually remove page-level `<style>` blocks and move remaining styles into named component classes.
- Replace emoji navigation icons with one icon set such as Lucide.
- Do a mobile-first polish pass on Supplier Dispatch, Shipper Booking Detail and Admin Marketplace.
