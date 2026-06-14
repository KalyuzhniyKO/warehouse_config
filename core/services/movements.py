from core.models import StockMovement


def trusted_business_movements(queryset=None):
    """Return business operations, excluding cancelled originals and reversals."""
    queryset = queryset if queryset is not None else StockMovement.objects.all()
    return queryset.filter(is_cancelled=False, reversal_of__isnull=True)
