# Job-based driver + vehicle dispatch update

Changed supplier dispatch from permanent driver-vehicle pairings to job-based assignment.

## New flow
1. Supplier accepts booking.
2. Dispatch board shows available drivers separately.
3. Dispatch board shows eligible available vehicles separately.
4. Supplier chooses one driver and one vehicle for that job.
5. Backend validates driver availability, vehicle availability, and Kargo equipment fit.
6. Driver app receives that job with the selected vehicle and instructions.

Drivers are no longer required to have a default vehicle.
