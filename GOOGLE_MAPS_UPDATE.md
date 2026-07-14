# Google Maps Integration Update

Implemented Google Maps support for FreightFlow Nexus.

## Added
- `GOOGLE_MAPS_API_KEY` config value loaded from `.env` / environment.
- Global Jinja variable `google_maps_key` available to templates.
- Google Places autocomplete on the shipper new shipment page.
- Backend Google Geocoding + Distance Matrix helper service.
- Booking address validation now prefers Google Maps when configured.
- Route distance calculation now prefers Google Distance Matrix when configured.
- Supplier driver tracking page now renders a Google map when the key is configured.
- Driver app tracking tab now renders a Google map when the key is configured.

## Deployment note
For Render/production, add `GOOGLE_MAPS_API_KEY` as an environment variable instead of relying on the local `.env` file.

## Recommended API restrictions
Restrict the key in Google Cloud Console to only:
- Maps JavaScript API
- Places API
- Geocoding API
- Distance Matrix API

Also restrict by domain for production.
