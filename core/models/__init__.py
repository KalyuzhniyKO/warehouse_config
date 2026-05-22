"""
core.models package

Split into submodules for maintainability. All public names are re-exported here
so every existing import (from core.models import X, from ..models import X, etc.)
continues to work without any changes.
"""

from .base import ActiveModel, SystemSettings
from .barcodes import BarcodeRegistry, BarcodeSequence
from .directories import Category, Recipient, Unit, UsagePlace
from .inventory import InventoryCount, InventoryCountLine
from .labels import LabelTemplate, PrintJob, Printer
from .stock import StockBalance, StockMovement
from .warehouse import Item, Location, Warehouse

__all__ = [
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
    "PrintJob",
    "Printer",
    # stock
    "StockBalance",
    "StockMovement",
    # warehouse
    "Item",
    "Location",
    "Warehouse",
]
