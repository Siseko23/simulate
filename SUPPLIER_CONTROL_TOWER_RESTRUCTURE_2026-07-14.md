# Supplier Control Tower Restructure

Implemented:
- Supplier landing page replaced with fleet control tower.
- Capacity calculation considers active assignments, accepted/unassigned jobs, maintenance and expired roadworthy status.
- Separate Trailer assets with type, payload, CBM, location and compliance dates.
- Horse + trailer + driver assignment support in Dispatch.
- Fleet assignment schedule with departure, ETA, projected location and availability time.
- Route Planner and projected capacity views.
- Return-load gap detection and configurable radius/home-depot/deadhead settings.
- Return-load opportunity scoring using collection distance, home-depot alignment and trailer compatibility.
- Maintenance module that removes assets from available capacity.
- Supplier navigation reorganised around Control Tower, Jobs, Dispatch, Route Planner, Return Loads, Fleet, Capacity, Maintenance and Compliance.
- Additive database tables created automatically with db.create_all().

Verification:
- Python compilation passed.
- New database tables created successfully.
- Public homepage returned HTTP 200.
- Supplier login and all five new supplier pages returned HTTP 200.
