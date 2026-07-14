# FreightFlow Nexus - Emoji Cleanup

Removed emoji/pictographic characters from the runtime website files.

Scope:
- HTML templates
- Runtime CSS/JS
- Python user-facing strings where emoji symbols appeared

Changes:
- Replaced sidebar emoji icons with clean text-safe labels.
- Removed emoji from buttons, alerts, Kargo messages, dashboards, tracking pages, onboarding, waybills and admin/supplier/shipper/driver pages.
- Replaced decorative symbols with ASCII-safe wording where needed.
- Verified no emoji-range characters remain in website templates/static files.
- Verified Python files compile successfully.

Note:
- Vehicle photos and product imagery were left unchanged.
- Functional routes and backend logic were not intentionally changed.
