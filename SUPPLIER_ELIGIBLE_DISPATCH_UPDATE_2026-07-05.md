# Supplier Eligible Dispatch Update - 2026-07-05

Implemented supplier dispatch eligibility rules.

## What changed

- After accepting a booking, supplier is redirected to Dispatch.
- Dispatch now builds eligible driver + vehicle combinations per booking.
- Driver must be available, have portal access, and not already be assigned to an active job.
- Vehicle must be available and not already assigned to an active job.
- Vehicle must fit the shipment using Kargo equipment fit logic.
- Supplier sees pair options like `Thabo - Bakkie / LDV - ND 123 456`.
- Non-eligible vehicles are visible under a collapsed explanation list, but cannot be assigned.
- Backend validates the same eligibility rules on POST, so UI bypassing is blocked.

## Flow

Supplier accepts booking -> PO generated -> Dispatch board -> eligible pairs shown -> assign driver + vehicle -> driver notified -> vehicle and driver marked On Trip.
