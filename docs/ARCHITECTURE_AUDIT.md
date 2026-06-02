# Architecture audit and refactoring roadmap

This audit captures the current warehouse application structure after the recent stock authorship, cancellation, warehouse-access, warehouse-only UI, analytics, and localization stabilization work. It is intentionally a documentation-only planning artifact: it identifies safe seams for future refactoring, but it does not prescribe a large rewrite in a single change.

## 1. Current architecture overview

### Current physical structure

The project is already split into Django-oriented packages under `core/`, with separate model, form, view, service, permission, template-tag, and test modules. The split is useful, but several modules have grown into feature clusters that now mix multiple responsibilities.

Notable current files by size and responsibility:

| Area | Current files | Notes |
| --- | --- | --- |
| Stock operations and movement UI | `core/views/stock_operations.py`, `core/views/stock_movements.py`, `core/views/stock_lists.py`, `core/forms/stock_operations.py`, `core/services/stock.py`, `templates/core/stock*.html` | Operation entry views now stay in `stock_operations.py`, while movement list/result/print/cancel views live in `stock_movements.py`; stock services still own mutations. |
| Warehouse access | `core/services/warehouse_access.py`, `core/models/warehouse_access.py`, warehouse-aware forms/views/tests | Central service exists, but callers still need to coordinate access filtering in views, forms, analytics, and templates. |
| Audit log | `core/models/audit.py`, `core/services/audit.py`, `templates/core/management/audit_log.html`, stock/admin callers | Audit model and service are present and used by stock cancellation and management flows. |
| Movement cancellation | `core/services/stock.py`, `core/forms/stock_operations.py`, `core/views/stock_movements.py`, `templates/core/stock_movement_cancel.html` | Cancellation is auditable and protected; its UI now lives with the other stock movement views while the service implementation remains in the broader stock service. |
| Analytics | `core/views/analytics.py`, `core/forms/analytics.py`, `core/services/analytics/`, `core/services/analytics_presets.py`, `templates/core/management/analytics*.html` | Feature is separated from stock views, and analytics service internals are split into filters, summaries, data quality, and export helper modules with package-level compatibility imports. |
| Inventory | `core/models/inventory.py`, `core/forms/inventory.py`, `core/views/inventory.py`, `core/services/inventory.py`, `templates/core/inventory*.html` | Better bounded than stock operations, with service-backed completion logic. |
| User management | `core/views/management.py`, `core/forms/management.py`, `templates/core/management/users.html`, `templates/core/management/user_form.html`, `templates/core/management/user_password_form.html` | User CRUD, role presentation, warehouse access assignment, and management dashboard concerns are close together. |
| Directories | `core/models/directories.py`, `core/forms/directories.py`, `core/views/directories.py`, directory templates | Large but understandable CRUD surface for units, categories, items, warehouses, locations, and recipients. |
| Printers and labels | `core/views/labels.py`, `core/forms/labels.py`, `core/services/labels.py`, `core/services/printers.py`, label/printer templates | Label rendering and printer synchronization are service-backed, but the UI layer remains sizeable. |
| Localization | `locale/uk/LC_MESSAGES/django.po`, `locale/ru/LC_MESSAGES/django.po`, `locale/en/LC_MESSAGES/django.po`, other locale catalogs | Active catalogs are large and contain fuzzy/legacy entries that should be cleaned carefully. |
| Dashboard and navbar | `core/views/dashboard.py`, `templates/core/dashboard.html`, `templates/base.html`, `core/templatetags/core_extras.py` | The dashboard and header are compact for users but contain repeated card/user-menu markup and template-level permission checks. |

### Logical modules

#### Stock operations

Stock operations cover receive, issue, return, write-off, transfer, and initial balance flows. The important architectural pattern is that stock mutations are performed through `core/services/stock.py` rather than directly inside templates or models. The current view/form surface is broad: operation forms normalize warehouse/location choices, support self-service behavior, handle barcode lookup context, produce result pages, and coordinate success/error messages.

#### Warehouse access

Warehouse access is represented explicitly through `UserWarehouseAccess` and centralized query helpers in `core/services/warehouse_access.py`. It scopes accessible warehouses and stock movements for non-superusers, and it supports delegation checks for assigning warehouse access. The access rules are also reflected in forms, stock lists, analytics filters, and management UI.

#### Audit log

Audit logging is modeled separately and has a service helper for creating log entries. Recent work made authorship and cancellation auditable, which is a strong base for compliance and incident review. The audit UI is management-oriented, with access guarded separately from regular stock forms.

#### Movement cancellation

Movement cancellation is implemented as a reversal-style domain operation: the original movement is marked cancelled, a reversal movement is created, balances are adjusted, and the action is logged. This is safer than deleting movement history. The cancellation workflow currently sits in the stock service and stock operation views, making it a good candidate for a narrow extraction later.

#### Analytics

Analytics has a dedicated view, form, service package, presets helper, management templates, and tests. It covers scoped filtering, summary metrics, daily movement data, top issued items, usage places, recipients, inactive stock, recent movements, detail pages, data quality, and CSV/XLSX export support. Service internals now live in focused `core/services/analytics/` modules while `core.services.analytics` remains the stable import surface.

#### Inventory

Inventory is a distinct feature with its own model, form, view, service, and templates. Service functions create counts, update actual quantities, and complete inventory counts through stock adjustments. This separation should be preserved when refactoring stock and analytics.

#### User management

Management user flows create and update application users, roles, active state, passwords, and warehouse access. The forms contain important safety checks around superuser accounts, role choices, and delegated warehouses. Those checks are business rules and should not be lost during any UI split.

#### Directories

Directories provide the master data used by stock, inventory, labels, and analytics: units, categories, items, warehouses, locations, and recipients/usage places. Directory views and forms already live in their own modules, but they remain large because they include validation, archive behavior, barcode behavior, and CRUD screens for several model families.

#### Printers and labels

Printer and label features include CUPS discovery/synchronization, test printing, label template configuration, item label PDF generation, and print jobs. Hardware and PDF behavior is correctly concentrated in services, while forms/views/templates expose the management workflow.

#### Localization

Localization is an active part of the product. Ukrainian, Russian, and English catalogs are large, and additional locale catalogs exist. Because role names, management wording, and warehouse-only UI labels are business-facing, translation cleanup should be handled as a dedicated refactor PR with tests and manual review.

#### Dashboard/navbar

The dashboard and navbar define the first user experience for warehouse administrators and storekeepers. They currently combine navigation structure, role-aware visibility, repeated card markup, user presentation, language controls, and PWA/header metadata. This is a good low-risk place to start refactoring because include extraction can preserve behavior while reducing template duplication.

## 2. Strong points

- **Stock mutations go through a service layer.** Receive, issue, return, write-off, transfer, adjustment, and cancellation behavior is concentrated in stock services instead of being scattered across templates.
- **Audit logging exists.** A dedicated audit model and service make sensitive changes traceable.
- **Tests are extensive.** The suite covers stock UI, stock services, movement cancellation, warehouse access, analytics, localization, management, directories, labels, printers, inventory, production safety, and PWA behavior.
- **Warehouse access exists as a first-class concept.** User-to-warehouse access and delegation are modeled explicitly and supported by service helpers.
- **Cancellation is auditable and reversible.** Stock movements are not hard-deleted; cancellation creates an explicit reversal and stores cancellation metadata.
- **Analytics is covered by tests.** Analytics behavior is tested at both service/view levels, including warehouse-scoped behavior and dashboard expectations.
- **Default technical locations exist.** Warehouse-only operation mode can rely on default locations without deleting the underlying location model or movement history.
- **Roles and common permissions have helpers.** Role display names/descriptions and named permission helpers are centralized enough to support warehouse-only UI language and safer permission audits.

## 3. Weak points / risks

### Large and complex files

The following files are the largest current maintenance hotspots:

- `core/views/stock_operations.py` is smaller after moving movement list/result/print/cancel views to `core/views/stock_movements.py`, but it still carries stock operation forms, self-service token handling, and barcode context.
- `core/services/stock.py` is approximately 570 lines and combines stock mutation primitives, public operation functions, balance updates, cancellation eligibility, cancellation deltas, reversal movement creation, and audit logging calls.
- `core/forms/stock_operations.py` is approximately 520 lines and contains operation-specific form logic, warehouse/location scoping, barcode defaults, recipient/comment requirements, transfer validation, initial balance, and cancellation reason validation.
- `core/views/directories.py`, `core/views/management.py`, `core/views/analytics.py`, `core/forms/management.py`, and `core/forms/directories.py` are each large enough that future unrelated changes can collide.
- `templates/base.html` is approximately 370 lines and includes app shell, navbar, language controls, user menu, role-aware links, and PWA metadata.
- The active translation catalogs are thousands of lines each, so unrelated UI changes can create noisy translation diffs.

### Business logic still inside views and forms

The service layer is present, but some decision logic still lives outside services:

- self-service storekeeper detection appears in view/template logic;
- form constructors and cleaners coordinate warehouse access, active querysets, default locations, and recipient requirements;
- management forms enforce important user/warehouse/superuser safety rules;
- analytics views normalize filters before calling analytics services;
- templates still check `user.is_superuser` and group membership directly for some actions.

This is acceptable for the current size, but it increases the risk of inconsistent behavior when a rule changes.

### Duplicated or repeated template structure

Dashboard and management templates repeatedly implement card-like links with the same HTML shape: icon, title, description, chevron, and URL. Similar status/badge patterns appear in stock movement and management user screens. Repetition makes visual changes expensive and raises the chance that one card or badge drifts from the others.

### Permissions are spread across layers

Permission concepts currently appear in several forms:

- constants, `GroupRequiredMixin`, and named helpers in `core/permissions.py`;
- warehouse access helpers in `core/services/warehouse_access.py`;
- cancellation helper in `core/services/stock.py`;
- `user.is_superuser` and group checks in templates;
- access-scoped querysets in views/forms/services.

The rules are generally correct, and centralized helpers now cover common Python call sites; remaining template-level checks should be migrated gradually in focused UI PRs.

### Translation catalogs contain legacy/fuzzy risk

The Ukrainian, Russian, and English catalogs are large and currently include many fuzzy entries. Some entries also preserve historical wording around superuser/root-related concepts. A translation cleanup should be isolated because catalog changes are noisy and can accidentally affect visible business terminology.

### Tests are strong but becoming large

Large test modules are a good sign of coverage, but they are becoming harder to navigate. `core/tests/test_stock_operations_ui.py` is over 2,000 lines, while localization, inventory, management, stock services, directories, labels, permissions, and warehouse access tests are also sizeable. This can slow focused development because unrelated fixtures and assertions live together.

### Coupling between warehouse access, analytics, and stock forms

Warehouse access affects stock forms, stock movement lists, analytics filters, inventory choices, and management user assignment. Analytics also depends on movement semantics and warehouse filtering. This coupling is expected, but future changes should keep access rules centralized and test both service-level and UI-level behavior.

## 4. Recommended target structure

The target structure should be reached incrementally. File moves should preserve public imports where possible by adding compatibility imports in package `__init__.py` files or thin wrapper modules during transition PRs.

```text
core/
  views/
    stock_operations.py        # receive/issue/return/write-off/transfer forms and results
    stock_movements.py         # movement list, print, cancel, movement-specific helpers
    management_users.py        # user list/create/update/password/warehouse access
    management_dashboard.py    # management landing/settings/help/report entry points
    analytics.py               # analytics pages only; delegate calculations to services
    inventory.py
    directories.py
    printers.py
    labels.py

  forms/
    stock_operations.py        # stock operation input forms only
    management_users.py        # user/role/warehouse-access forms
    analytics.py               # analytics filter/export forms
    directories.py
    inventory.py
    labels.py

  services/
    stock.py                   # public stock mutation API and compatibility imports
    stock_cancellation.py      # cancellation eligibility, deltas, reversal, audit call
    audit.py
    warehouse_access.py
    analytics/
      filters.py               # normalize filters and build scoped querysets
      summaries.py             # summary cards, charts, top lists, detail summaries
      data_quality.py          # missing/invalid data checks
      exports.py               # CSV/export row preparation

  templates/core/includes/
    dashboard_card.html
    user_menu.html
    filter_panel.html
    movement_status_badge.html
    warehouse_access_badge.html
```

Additional recommendations:

- Keep `core/services/stock.py` as the stable public import location until all callers are migrated.
- Keep URL names stable during view splits.
- Prefer extracting templates before moving Python logic.
- Add small permission helpers before changing permission call sites.
- Avoid moving tests and implementation in the same PR unless the move is mechanical and the test suite remains unchanged.

## 5. Suggested refactoring PR sequence

### PR 1: Extract dashboard cards and user dropdown into include templates

Create include templates for repeated dashboard cards and the authenticated user menu. Replace repeated markup in `templates/core/dashboard.html`, `templates/core/management/dashboard.html`, and the relevant part of `templates/base.html` without changing URLs, text, permissions, or CSS classes. This is the safest first refactor because it is mostly HTML extraction.

### PR 2: Split stock movement views from stock operation views — completed

Moved movement list, operation result, print, and cancel views into `core/views/stock_movements.py`. URL names and service behavior stayed stable.

### PR 3: Move cancellation logic from `stock.py` into `stock_cancellation.py` while keeping public API stable — completed

Cancellation eligibility, reversal delta helpers, reversal movement creation, negative-balance validation, and audit payload construction now live in `core/services/stock_cancellation.py`. `core/services/stock.py` re-exports the public cancellation helpers so existing imports continue to work during the transition.

### PR 4: Split analytics service into small modules — completed

Analytics internals now live in `core/services/analytics/`:

- `filters.py` for filter normalization and scoped movement/balance querysets;
- `summaries.py` for dashboard summary metrics and top lists;
- `data_quality.py` for data quality checks;
- `exports.py` for CSV/export row preparation.

Keep package-level re-exports in `core/services/analytics/__init__.py` so existing `core.services.analytics` imports remain stable.

### PR 5: Split management user forms/views from general management dashboard — completed

User CRUD, password update, role assignment, and warehouse access assignment now live in `core/views/management_users.py` and `core/forms/management_users.py`. `core/views/management.py` retains dashboard/settings/help concerns and compatibility re-exports, while `core/forms/management.py` keeps settings plus compatibility imports.

### PR 6: Create centralized permission helpers — completed

Added named helpers for commonly audited rules:

- `can_manage_users(user)`;
- `can_view_audit(user)`;
- `can_cancel_movement(user, movement=None)`;
- `can_assign_warehouse_access(user, warehouse=None)`;
- `can_view_warehouse_data(user, warehouse=None)`;
- `can_view_analytics(user)`;
- `can_manage_directories(user)`;
- `can_print_labels(user)`;
- `can_manage_settings(user)`.

The helpers live in `core/permissions.py`. Safe Python call sites for audit access, movement cancellation, analytics access, management user access, directory-management dashboard flags, and warehouse-data dashboard flags now use the helpers where behavior was clearly equivalent. Broad template migration remains intentionally out of scope.

### PR 7: Clean active translation catalogs and remove/disable unused legacy locales if present

Clean fuzzy entries in active catalogs and review old wording. If unused legacy locales are present, remove or disable them only after confirming product requirements. Keep this PR isolated because translation diffs are noisy.

#### Translation catalog audit — completed

- Locale settings currently use `LANGUAGE_CODE = os.getenv("DJANGO_LANGUAGE_CODE", "uk")`, `LANGUAGES = [("uk", "Українська"), ("en", "English"), ("ru", "Русский"), ("it", "Italiano"), ("pl", "Polski")]`, and `LOCALE_PATHS = [BASE_DIR / "locale"]`.
- Locale directories found under `locale/`: `de`, `en`, `es`, `fr`, `it`, `pl`, `pt`, `ru`, `tr`, and `uk`.
- Active locale directories according to `LANGUAGES`: `uk`, `en`, `ru`, `it`, and `pl`.
- Legacy/inactive locale directories currently present but not listed in `LANGUAGES`: `de`, `es`, `fr`, `pt`, and `tr`.
- Fuzzy entry counts in active catalogs, counted as lines containing `#, fuzzy`:
  - `locale/uk/LC_MESSAGES/django.po`: 215
  - `locale/en/LC_MESSAGES/django.po`: 198
  - `locale/ru/LC_MESSAGES/django.po`: 118
  - `locale/it/LC_MESSAGES/django.po`: 212
  - `locale/pl/LC_MESSAGES/django.po`: 0
- Root/superuser wording search summary for active catalogs:
  - The exact lowercase term `root` was not found in any active catalog.
  - The term `superuser` was found in every active catalog.
  - The terms `суперкористувач` and `суперпользователь` were not found in any active catalog.
  - Owner/admin/user wording is present in the active catalogs through source `msgid` entries and/or translated `msgstr` entries: `Власник`, `Owner`, `Владелец`, `Адміністратор`, `Administrator`, `Администратор`, `Користувач`, `User`, and `Пользователь` were found where applicable for the current Ukrainian source catalog and English/Russian translations.
- No translation strings or fuzzy markers were changed in this audit. Actual cleanup should be done in follow-up PRs per locale.
- Russian role/root wording cleanup completed for the active Russian catalog: visible role labels remain `Владелец`, `Администратор`, and `Пользователь`, while old `superuser` wording was removed from the reviewed user-facing system-administrator notice. No broad Russian catalog cleanup was done. Follow-up cleanup remains for the `uk`, `en`, and `it` active catalogs.
- Ukrainian role/root wording cleanup completed for the active Ukrainian catalog: visible role labels remain `Власник`, `Адміністратор`, and `Користувач`, while old `superuser` wording was removed from the reviewed user-facing system-administrator notice. No broad Ukrainian catalog cleanup was done. Follow-up cleanup remains for the `en`, `it`, and `pl` active catalogs.

### PR 8: Split large tests into focused test modules by feature

Split the largest test modules into focused modules such as stock operation forms, stock operation views, self-service UI, cancellation, movement lists, management users, localization roles, analytics filters, and analytics exports. Keep assertions intact and avoid weakening tests.

## 6. Risk control rules

- Do one refactor PR at a time.
- Do not change business behavior during a pure refactor.
- Run the full test suite after every refactor PR.
- Never weaken or delete tests just to make a refactor pass.
- Preserve migration compatibility; pure refactor PRs should not create migrations.
- Keep public service APIs stable, or add compatibility wrappers during module moves.
- Never hard-delete stock movements; preserve auditable movement history.
- Do not use the word `root` in user-facing UI.
- Keep URL names stable unless a dedicated routing migration is planned.
- Prefer mechanical extraction with before/after tests over opportunistic cleanup.
- Review warehouse-scoped behavior whenever touching stock, analytics, inventory, or user management.
- Review translations in the active languages whenever moving user-facing strings.

## 7. Immediate next recommended PR

The first real refactor should be: **Extract dashboard cards and user menu includes**.

Suggested Codex task for that PR:

> Create `templates/core/includes/dashboard_card.html` and `templates/core/includes/user_menu.html`. Replace repeated dashboard card markup in the main dashboard and management dashboard, and replace the authenticated user dropdown markup in `templates/base.html`. Preserve all existing translated strings, URL names, permissions, CSS classes, ARIA attributes, and visual behavior. Do not change Python business logic. Run `python manage.py check` and `python manage.py test`; no migrations should be created.
