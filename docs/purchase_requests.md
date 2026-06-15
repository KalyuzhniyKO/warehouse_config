# Purchase requests

The purchase requests module follows the existing Google Sheet order-tracking
structure: request date, item name, need description, quantity, unit, optional
unit price in UAH, calculated total, order type, approval status, payment
status, delivery status, and an optional product URL.

The sheet's `Код` column is intentionally not used. Purchase requests also do
not contain order numbers, invoice numbers, invoice dates, payment amounts, or
other accounting workflow fields.

Workflow:

1. A user with warehouse access creates and edits a draft request and selects
   whether it is emergency, urgent, or planned.
2. The requester sends the draft for approval.
3. A warehouse administrator or superuser approves or rejects the request.
4. An approved request can be marked as ordered.
5. A warehouse administrator or superuser can cancel a request.

Approval status records whether the request is pending, approved, or rejected.
Payment and delivery statuses are tracking fields only. Changing them never
creates a stock movement and never changes stock balance.

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
