# Google Places Address Autofill Update

Implemented on the shipper shipment page.

## What changed
- Collection and delivery address inputs now request full Google Places details:
  - formatted address
  - latitude/longitude
  - address components
  - place ID
- When the user selects a Google suggestion, the form auto-fills:
  - City
  - Province
  - Postal code
  - GPS latitude/longitude
- Address hints now show a Google verified badge plus city/province/postal/GPS details.
- Autofilled city/province/postal inputs are visually highlighted.
- Pressing Enter while selecting a Google suggestion no longer submits the form too early.
- If the user edits the address after selecting a Google place, the stale GPS coordinates are cleared until they choose a suggestion again.

## Required Google Cloud APIs
Enable these APIs on the key:
- Maps JavaScript API
- Places API
- Geocoding API
- Directions API

If autocomplete does not appear, check API restrictions and billing in Google Cloud Console.
