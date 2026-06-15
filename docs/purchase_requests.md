# Purchase requests

The purchase requests module records planned purchases and their internal
approval state. Creating and approving a request does not create stock
movements or change stock balances.

Workflow:

1. A user with warehouse access creates and edits a draft request.
2. The requester sends the draft for approval.
3. A warehouse administrator or superuser approves or rejects the request.
4. An approved request can be marked as ordered.
5. A warehouse administrator or superuser can cancel a request.

Approved and ordered requests may optionally be linked to normal stock receive
operations. Linked receives update the request to `partially_received` or
`received`. Manual receives without a purchase request continue to work
unchanged.

Received and remaining quantities are derived from active linked receive
movements. Cancelled movements and cancellation/reversal rows are excluded.

Warehouse administrators and superusers can view and manage all requests.
Other users with warehouse access can view and edit only their own draft
requests.
