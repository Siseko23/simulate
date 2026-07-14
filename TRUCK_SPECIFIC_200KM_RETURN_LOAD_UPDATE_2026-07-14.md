# Truck-specific 200 km return-load update

- Every active fleet assignment now stores the exact projected drop-off coordinates.
- Each truck receives its own return-load search centred on its delivery point.
- Open loads are filtered to collections within the supplier-configured radius (default 200 km).
- Matching checks collection timing, payload, horse/trailer compatibility, and home-depot alignment.
- A selected opportunity is reserved against that exact truck through `next_booking_id`.
- The same job cannot be reserved by multiple trucks.
- Existing SQLite demo databases receive additive coordinate and next-load columns automatically.
