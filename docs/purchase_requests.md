# Purchase requests

The purchase requests module follows the existing Google Sheet order-tracking
structure: request date, item name, need description, quantity, unit, optional
unit price in UAH, calculated total, order type, approval status, payment
status, delivery status, and an optional product URL.

The sheet's `Код` column is intentionally not used. Purchase requests also do
not contain order numbers, invoice numbers, invoice dates, payment amounts, or
other accounting workflow fields.

Workflow:

1. A user with warehouse access creates a simple request with the needed item
   name, quantity, unit, need description, optional product URL, and order type.
   The requester is set automatically from the logged-in account; it is not an
   editable field.
2. New requests start as pending approval. The create page does not show
   approval, payment, delivery, audit, receiving, or existing request tables.
3. A warehouse administrator or superuser approves or rejects the request with
   action buttons. Approval writes `approved_by` and `approved_at`; rejection
   writes `rejected_by`, `rejected_at`, and an optional rejection comment.
4. An approved request can be marked as ordered.
5. A warehouse administrator or superuser can cancel a request.

The requested item field accepts either an existing item name or new free text.
If the typed name exactly matches an active item, the request is linked to that
item. New text does not create an item automatically.

The unit field is a normal text field with existing units offered for convenience.
Users may type a new unit value without changing the unit directory.

Approval status records whether the request is pending, approved, or rejected.
Payment and delivery statuses are tracking fields only. Changing them never
creates a stock movement and never changes stock balance.

Normal edit forms do not expose requester or approval audit fields. Approval and
rejection audit data is populated only from the logged-in user performing the
action.

Approved and ordered requests may optionally be linked to normal stock receive
operations. Linked receives update the request to `partially_received` or
`received`. Manual receives without a purchase request continue to work
unchanged.

Received and remaining quantities are derived from active linked receive
movements. Cancelled movements and cancellation/reversal rows are excluded.

Warehouse administrators and superusers can view and manage all requests.
Other users with warehouse access can view and edit only their own draft
requests.

Actual stock balance changes only through the normal stock receive flow.

Deployment after updating the application:

```sh
python manage.py migrate
```
