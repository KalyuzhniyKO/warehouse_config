from core.permissions import can_create_purchase_requests, can_view_purchase_requests


def purchase_request_permissions(request):
    return {
        "can_create_purchase_requests": can_create_purchase_requests(request.user),
        "can_view_purchase_requests": can_view_purchase_requests(request.user),
    }
