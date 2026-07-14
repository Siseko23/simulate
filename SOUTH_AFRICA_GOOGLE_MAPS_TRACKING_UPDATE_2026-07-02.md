# South Africa Google Maps Tracking Update - 2026-07-02

Implemented a proper South African route map experience across FreightFlow.

## Updated
- Added `app/static/css/ffn-sa-map.css`
- Added `app/static/js/ffn-sa-map.js`
- Updated `app/templates/landing.html`
- Updated `app/templates/public/landing.html`
- Updated `app/templates/shipper/dashboard.html`
- Updated `app/templates/shipper/booking_detail.html`
- Updated `app/templates/shipper/tracking.html`
- Updated `app/templates/public_tracking.html`

## What changed
- Replaced fake/vector route lines with a Google Maps-ready South Africa map component.
- Added dark Google Maps styling to match FreightFlow's red/black design language.
- Added Johannesburg to Durban default route preview using South African city coordinates.
- Added origin, destination and live driver markers.
- Added route rendering using Google Directions API when `GOOGLE_MAPS_API_KEY` is available.
- Added branded fallback map if Google Maps is unavailable.
- Added map overlays for status, route summary and live route chips.

## Notes
- The map component uses `google_maps_key` from the existing app context.
- If the API key is missing, pages still show a professional FreightFlow fallback map instead of a broken blank box.
- Existing driver Socket.IO live tracking remains intact.
