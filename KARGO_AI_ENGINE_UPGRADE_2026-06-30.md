# Kargo AI Engine Upgrade — 2026-06-30

## What changed
- Replaced separate/fragmented AI logic with one shared `app/services/ai_engine.py` Kargo engine.
- Quote ranking and the FreightFlow AI Assistant now feed from the same scoring/explanation functions.
- Removed runtime dependency on a third-party AI API key for demo answers.
- Added logistics-aware scoring dimensions:
  - price competitiveness
  - supplier performance
  - supplier depot proximity to pickup city
  - equipment/trailer fit
  - available driver/vehicle signal
  - route/load risk rating
- Added equipment fit profiles for Bakkie/LDV, Panel Van, 4-Ton, 8-Ton, Curtainsider, Superlink, Flatdeck, Lowbed, Reefer and Skeletal Trailer.

## Why it matters
Kargo is now not just a chat assistant. It is the same intelligence layer behind supplier ranking, vehicle recommendations, quote explanations and shipper advice.

## Remaining future improvement
Persist pickup/dropoff lat/lng and supplier depot lat/lng in the DB so proximity scoring can use exact Google Places coordinates instead of city-coordinate fallback.
