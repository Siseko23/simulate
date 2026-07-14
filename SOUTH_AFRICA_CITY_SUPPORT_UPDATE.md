# South Africa City Support Update

## Issue fixed
The shipment flow still had an old demo whitelist of supported cities. Valid Google Places results such as `Krugersdorp` were being rejected with:

> Delivery city 'Krugersdorp' is not supported in this demo.

## Changes made
- Removed the backend city whitelist as a blocking rule.
- Kept `SA_CITIES` only as form suggestions/datalist hints.
- Added GPS-based distance fallback using Places latitude/longitude fields.
- Added an expanded coordinate fallback table for common South African cities.
- Added a last-resort demo-safe distance fallback so valid SA city names do not break the quote flow when Google returns REQUEST_DENIED.
- Added Krugersdorp to the demo route and coordinate fallbacks.

## Tested
A Johannesburg/Sandton to Krugersdorp shipment validation now passes with no city support error and returns a valid distance.

## Production note
For a production launch, keep Google Places + Distance Matrix enabled and restrict the API key by domain/IP. The fallback is intentionally demo-safe so the system remains usable during presentations or when Google billing/API permissions are not ready.
