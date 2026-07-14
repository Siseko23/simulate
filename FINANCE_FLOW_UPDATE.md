# FreightFlow Nexus Finance Flow Update

This version adds stricter marketplace-style finance controls:

1. **Shipper pays FreightFlow first**
   - Payment moves the booking to `Pending Supplier Acceptance`.
   - Timeline event records that funds are held by the platform.

2. **Supplier must accept**
   - Admin does not confirm bookings for suppliers.
   - Supplier acceptance creates a supplier Purchase Order.

3. **Supplier payout is locked**
   - Supplier can only upload an invoice after the booking is `Delivered` and POD is signed/scanned.
   - Finance can only approve a PO after supplier invoice upload, delivery, and POD.
   - Payout can only be released once the PO is approved.
   - Paid POs cannot be paid again.

4. **Bulk payout route is safer**
   - It only pays approved, unpaid POs.
   - Delivered bookings alone are not enough to trigger supplier payment.

5. **Booking timeline improved**
   - Escrow funded
   - Supplier PO created
   - Supplier invoice uploaded
   - Supplier invoice approved/rejected
   - Supplier paid

Operational flow remains:
`Quote Selected → Payment to Platform → Supplier Accepts → Confirmed → Dispatch → Delivery → POD → Supplier Invoice → Admin Verify → Supplier Paid`
