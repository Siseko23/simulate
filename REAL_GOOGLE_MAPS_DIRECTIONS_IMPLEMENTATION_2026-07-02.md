# Real Google Maps Directions Implementation

Implemented the real Google Maps rendering plan for FreightFlow tracking components.

## What changed
- `app/static/js/ffn-sa-map.js` now uses Google Maps `DirectionsService` and `DirectionsRenderer` as the primary route renderer.
- Johannesburg to Durban route is requested from Google, with Pietermaritzburg as the live/current truck waypoint in control-tower mode.
- Control tower maps use Google HYBRID/Satellite view with traffic layer enabled.
- Added a custom SVG truck marker placed at the live driver position.
- Added origin and destination markers.
- Added Google route distance/duration summaries when Directions API returns successfully.
- Fallback drawing is now only shown when Google Maps is unavailable or the API request fails.
- Context processor now reads either `GOOGLE_MAPS_API_KEY` or `GOOGLE_MAPS_KEY`.
- Google Maps scripts now load with `v=weekly`.

## Important
For this to show the real map on Render, the environment must include either:

```text
GOOGLE_MAPS_API_KEY=your_key
```

or

```text
GOOGLE_MAPS_KEY=your_key
```

The key must have Maps JavaScript API and Directions API enabled, and billing/domain restrictions must allow the deployed Render URL.
