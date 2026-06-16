from core.permissions import (
    can_access_warehouse,
    can_approve_purchase_requests,
    can_create_purchase_requests,
    can_update_purchase_request_tracking,
    can_view_purchase_requests,
)


def purchase_request_permissions(request):
    return {
        "can_access_warehouse": can_access_warehouse(request.user),
        "can_approve_purchase_requests": can_approve_purchase_requests(request.user),
        "can_create_purchase_requests": can_create_purchase_requests(request.user),
        "can_update_purchase_request_tracking": can_update_purchase_request_tracking(
            request.user
        ),
        "can_view_purchase_requests": can_view_purchase_requests(request.user),
    }
