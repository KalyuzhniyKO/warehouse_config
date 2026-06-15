# Purchase requests

The purchase requests module records planned purchases and their internal
approval state. It does not create stock movements, change stock balances, or
receive goods.

Workflow:

1. A user with warehouse access creates and edits a draft request.
2. The requester sends the draft for approval.
3. A warehouse administrator or superuser approves or rejects the request.
4. An approved request can be marked as ordered.
5. A warehouse administrator or superuser can cancel a request.

Warehouse administrators and superusers can view and manage all requests.
Other users with warehouse access can view and edit only their own draft
requests.
