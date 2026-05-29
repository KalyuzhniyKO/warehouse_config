"""
core.models package

Split into submodules for maintainability. All public names are re-exported here
so every existing import (from core.models import X, from ..models import X, etc.)
continues to work without any changes.
"""

from .audit import AuditLog
from .base import ActiveModel, SystemSettings
from .barcodes import BarcodeRegistry, BarcodeSequence
from .directories import Category, Recipient, Unit, UsagePlace
from .inventory import InventoryCount, InventoryCountLine
from .labels import LabelTemplate, LabelTemplateElement, PrintJob, Printer
from .stock import StockBalance, StockMovement
from .warehouse import Item, Location, Warehouse
from .warehouse_access import UserWarehouseAccess

__all__ = [
    # audit
    "AuditLog",
    # base
    "ActiveModel",
    "SystemSettings",
    # barcodes
    "BarcodeRegistry",
    "BarcodeSequence",
    # directories
    "Category",
    "Recipient",
    "Unit",
    "UsagePlace",
    # inventory
    "InventoryCount",
    "InventoryCountLine",
    # labels
    "LabelTemplate",
    "LabelTemplateElement",
    "PrintJob",
    "Printer",
    # stock
    "StockBalance",
    "StockMovement",
    # warehouse
    "Item",
    "Location",
    "UserWarehouseAccess",
    "Warehouse",
]
