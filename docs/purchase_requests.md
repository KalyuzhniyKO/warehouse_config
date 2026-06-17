# Purchase requests

The purchase requests module follows the existing Google Sheet order-tracking
structure: request date, item name, need description, quantity, unit, optional
unit price in UAH, calculated total, order type, approval status, payment
status, delivery status, and an optional product URL.

The sheet's `Код` column is intentionally not used. Purchase requests also do
not contain order numbers, invoice numbers, invoice dates, payment amounts, or
other accounting workflow fields.

Workflow:

1. A user with `can_create_purchase_requests` creates a simple request with the
   needed item name, quantity, unit, need description, optional product URL, and
   order type. The requester is set automatically from the logged-in account; it
   is not an editable field.
2. New requests start as pending approval. The create page does not show
   approval, payment, delivery, audit, receiving, or existing request tables.
3. A user with `can_approve_purchase_requests` approves or rejects the request
   with action buttons. Approval writes `approved_by` and `approved_at`;
   rejection writes `rejected_by`, `rejected_at`, and an optional rejection
   comment.
4. An approved request can be marked as ordered.
5. A warehouse administrator or superuser can cancel a request.

The requested item field accepts either an existing item name or new free text.
If the typed name exactly matches an active item, the request is linked to that
item. New text does not create an item automatically.

The unit field is a normal text field with existing units offered for convenience.
Users may type a new unit value without changing the unit directory.

The purchase request list is table-first: filters live in the table header next
to their related columns. Date range filters are under the date column, search
is under the item/name column, and status/requester filters are under their
matching columns. Filters use GET parameters, so filtered links can be shared.

Approval status records whether the request is pending, approved, or rejected.
Payment and delivery statuses are tracking fields only. Changing them never
creates a stock movement and never changes stock balance.

## Permissions

Purchase requests use explicit Django permissions, exposed as clear checkboxes
on the internal **Користувачі та ролі** page and through Django Admin user/group
permissions:

- `can_access_warehouse` — user can enter and use the warehouse web interface.
- `can_view_purchase_requests` — user can open purchase request list/detail pages
  and export the visible list to Excel.
- `can_create_purchase_requests` — user can open and submit the create request
  form and sees the create button.
- `can_approve_purchase_requests` — user can approve or reject requests. The
  requester may approve their own request only when this permission is granted.
- `can_update_purchase_request_tracking` — user can update payment and delivery
  statuses without changing approval status or stock.

Superusers pass all permission checks. Existing `Адміністратор складу`
management users keep their previous purchase request abilities for backward
compatibility, but ordinary users can now be granted only the specific purchase
permissions they need.

Normal edit forms do not expose requester or approval audit fields. Approval and
rejection audit data is populated only from the logged-in user performing the
action.

Approved and ordered requests may optionally be linked to normal stock receive
operations. Linked receives update the request to `partially_received` or
`received`. Manual receives without a purchase request continue to work
unchanged.

Received and remaining quantities are derived from active linked receive
movements. Cancelled movements and cancellation/reversal rows are excluded.

Users with explicit view permission and management users can view the purchase
request list according to the configured business visibility. Users who can only
create requests can still work with their own requests. Direct POST requests for
create, approve/reject, tracking updates, and Excel export are checked on the
server side, not only hidden in templates.

Actual stock balance changes only through the normal stock receive flow.

Deployment after updating the application:

```sh
python manage.py migrate
```
