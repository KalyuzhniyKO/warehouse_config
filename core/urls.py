from django.urls import path
from django.utils.translation import gettext_lazy as _

from . import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path(
        "units/",
        views.directory_view(views.DirectoryListView, "unit"),
        name="unit_list",
    ),
    path(
        "units/create/",
        views.directory_view(views.DirectoryCreateView, "unit"),
        name="unit_create",
    ),
    path(
        "units/<int:pk>/edit/",
        views.directory_view(views.DirectoryUpdateView, "unit"),
        name="unit_update",
    ),
    path(
        "units/<int:pk>/archive/",
        views.directory_view(views.DirectoryArchiveView, "unit"),
        name="unit_archive",
    ),
    path(
        "units/<int:pk>/restore/",
        views.directory_view(views.DirectoryRestoreView, "unit"),
        name="unit_restore",
    ),
    path(
        "categories/",
        views.directory_view(views.DirectoryListView, "category"),
        name="category_list",
    ),
    path(
        "categories/create/",
        views.directory_view(views.DirectoryCreateView, "category"),
        name="category_create",
    ),
    path(
        "categories/<int:pk>/edit/",
        views.directory_view(views.DirectoryUpdateView, "category"),
        name="category_update",
    ),
    path(
        "categories/<int:pk>/archive/",
        views.directory_view(views.DirectoryArchiveView, "category"),
        name="category_archive",
    ),
    path(
        "categories/<int:pk>/restore/",
        views.directory_view(views.DirectoryRestoreView, "category"),
        name="category_restore",
    ),
    path(
        "recipients/",
        views.directory_view(views.DirectoryListView, "recipient"),
        name="recipient_list",
    ),
    path(
        "recipients/create/",
        views.directory_view(views.DirectoryCreateView, "recipient"),
        name="recipient_create",
    ),
    path(
        "recipients/<int:pk>/edit/",
        views.directory_view(views.DirectoryUpdateView, "recipient"),
        name="recipient_update",
    ),
    path(
        "recipients/<int:pk>/archive/",
        views.directory_view(views.DirectoryArchiveView, "recipient"),
        name="recipient_archive",
    ),
    path(
        "recipients/<int:pk>/restore/",
        views.directory_view(views.DirectoryRestoreView, "recipient"),
        name="recipient_restore",
    ),
    path(
        "items/",
        views.directory_view(views.DirectoryListView, "item"),
        name="item_list",
    ),
    path(
        "items/create/",
        views.directory_view(views.DirectoryCreateView, "item"),
        name="item_create",
    ),
    path(
        "items/<int:pk>/edit/",
        views.directory_view(views.DirectoryUpdateView, "item"),
        name="item_update",
    ),
    path(
        "items/<int:pk>/archive/",
        views.directory_view(views.DirectoryArchiveView, "item"),
        name="item_archive",
    ),
    path(
        "items/<int:pk>/restore/",
        views.directory_view(views.DirectoryRestoreView, "item"),
        name="item_restore",
    ),
    path(
        "warehouses/",
        views.directory_view(views.DirectoryListView, "warehouse"),
        name="warehouse_list",
    ),
    path(
        "warehouses/create/",
        views.directory_view(views.DirectoryCreateView, "warehouse"),
        name="warehouse_create",
    ),
    path(
        "warehouses/<int:pk>/edit/",
        views.directory_view(views.DirectoryUpdateView, "warehouse"),
        name="warehouse_update",
    ),
    path(
        "warehouses/<int:pk>/archive/",
        views.directory_view(views.DirectoryArchiveView, "warehouse"),
        name="warehouse_archive",
    ),
    path(
        "warehouses/<int:pk>/restore/",
        views.directory_view(views.DirectoryRestoreView, "warehouse"),
        name="warehouse_restore",
    ),
    path(
        "locations/",
        views.directory_view(views.DirectoryListView, "location"),
        name="location_list",
    ),
    path(
        "locations/create/",
        views.directory_view(views.DirectoryCreateView, "location"),
        name="location_create",
    ),
    path(
        "locations/<int:pk>/edit/",
        views.directory_view(views.DirectoryUpdateView, "location"),
        name="location_update",
    ),
    path(
        "locations/<int:pk>/archive/",
        views.directory_view(views.DirectoryArchiveView, "location"),
        name="location_archive",
    ),
    path(
        "locations/<int:pk>/restore/",
        views.directory_view(views.DirectoryRestoreView, "location"),
        name="location_restore",
    ),
    path(
        "stock-balances/",
        views.StockBalanceListView.as_view(),
        name="stockbalance_list",
    ),
    path("analytics/", views.AnalyticsRedirectView.as_view(), name="analytics"),
    path(
        "analytics/export.csv",
        views.AnalyticsCSVExportView.as_view(),
        name="analytics_export_csv",
    ),
    path(
        "analytics/export.xlsx",
        views.AnalyticsXLSXExportView.as_view(),
        name="analytics_export_xlsx",
    ),
    path("help/", views.HelpView.as_view(), name="help"),
    path("stock/inventory/", views.InventoryListView.as_view(), name="inventory_list"),
    path("stock/inventory/create/", views.InventoryCreateView.as_view(), name="inventory_create"),
    path("stock/inventory/<int:pk>/", views.InventoryDetailView.as_view(), name="inventory_detail"),
    path("stock/inventory/<int:pk>/count/", views.InventoryCountView.as_view(), name="inventory_count"),
    path("stock/receive/", views.StockReceiveView.as_view(), name="stock_receive"),
    path("stock/receive/<int:pk>/", views.StockReceiveResultView.as_view(), name="stock_receive_result"),
    path("stock/issue/", views.StockIssueView.as_view(), name="stock_issue"),
    path("stock/issue/<int:pk>/", views.StockIssueResultView.as_view(), name="stock_issue_result"),
    path("stock/initial/", views.InitialBalanceView.as_view(), name="stock_initial"),
    path("stock/movements/", views.StockMovementListView.as_view(), name="movement_list"),
    path("labels/item/<int:pk>/download/", views.ItemLabelDownloadView.as_view(), name="item_label_download"),
    path("labels/item/<int:pk>/print/", views.ItemLabelPrintView.as_view(), name="item_label_print"),
    path("settings/printers/", views.PrinterListView.as_view(), name="printer_list"),
    path("settings/printers/create/", views.PrinterCreateView.as_view(), name="printer_create"),
    path("settings/label-templates/", views.LabelTemplateListView.as_view(), name="labeltemplate_list"),
    path("settings/label-templates/create/", views.LabelTemplateCreateView.as_view(), name="labeltemplate_create"),
    path(
        "management/",
        views.ManagementDashboardView.as_view(),
        name="management_dashboard",
    ),
    path(
        "management/directories/",
        views.ManagementDirectoriesView.as_view(),
        name="management_directories",
    ),
    path(
        "management/users/",
        views.ManagementUsersView.as_view(),
        name="management_users",
    ),
    path(
        "management/settings/",
        views.ManagementSettingsView.as_view(),
        name="management_settings",
    ),
    path(
        "management/analytics/",
        views.AnalyticsView.as_view(),
        name="management_analytics",
    ),
    path(
        "management/analytics/export.csv",
        views.AnalyticsCSVExportView.as_view(),
        name="management_analytics_export_csv",
    ),
    path(
        "management/analytics/export.xlsx",
        views.AnalyticsXLSXExportView.as_view(),
        name="management_analytics_export_xlsx",
    ),
    path("management/help/", views.ManagementHelpView.as_view(), name="management_help"),
]
