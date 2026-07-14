# Order, QR, POD and finance flow update

Implemented final demo workflow changes:

- When shipper accepts a quote, an operational order is generated immediately.
- Label and collection/delivery QR links are available immediately after quote selection.
- Payment terms now support EFT/ad-hoc payment or account-credit release when the shipper has enough credit limit.
- Supplier acceptance confirms the job and notifies the shipper of collection expectations.
- Supplier dispatch treats driver and truck as separate trip-level choices: a driver can be paired with any available eligible vehicle for that job.
- Dispatch still validates driver availability, vehicle availability, and Kargo equipment fit.
- Driver app now shows pickup/delivery navigation links and allows multi-document POD capture.
- Delivery/POD completion moves supplier PO into invoice-pending queue for finance review.
- Shipper is notified when cargo is collected/delivered and when POD proof is captured.
