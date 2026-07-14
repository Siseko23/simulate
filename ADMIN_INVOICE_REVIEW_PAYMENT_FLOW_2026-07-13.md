# Admin invoice review and supplier payment flow

Implemented final finance workflow:

1. Supplier submits one invoice against a delivered purchase order.
2. Submission is blocked until complete structured delivery evidence exists.
3. The invoice is automatically linked to the PO, waybill, POD, signatures, GPS, driver completion report and delivery files.
4. All active admin users receive an invoice-package review notification.
5. Admin can separately view the supplier invoice, review the combined PDF, or download the complete ZIP evidence package.
6. Admin may approve or reject the package.
7. Supplier payment remains locked until admin approval.
8. Payment release validates supplier banking details, creates a permanent payout record and payment reference, marks the PO paid and notifies the supplier.
