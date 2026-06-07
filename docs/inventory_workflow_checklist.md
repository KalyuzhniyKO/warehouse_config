# Inventory workflow verification checklist

Use this checklist after inventory-related changes or before deploying a new
release. It describes the current non-blocking inventory workflow.

## How the workflow works

1. Open **Inventory** (`/stock/inventory/`) and create an inventory for a
   warehouse or, when needed, a specific location.
2. At creation time, every inventory line stores the current system quantity as
   its start snapshot.
3. Enter the physical quantity for each line as close as possible to the real
   count time. Saving the line records its `counted_at` timestamp.
4. Receive, issue, return, writeoff, and transfer operations remain available
   while the inventory is active.
5. The expected quantity is calculated as:

   `inventory start snapshot + net warehouse movements through counted_at`

6. The variance is calculated as:

   `physical counted quantity - expected quantity at counted_at`

7. Completing the inventory creates an `adjustment` movement only for a
   non-zero variance. Movements after `counted_at` remain normal stock
   movements and are not included in that line's variance.

## Reference examples

| Scenario | Snapshot | Movements through `counted_at` | Fact | Expected | Variance |
| --- | ---: | ---: | ---: | ---: | ---: |
| Issue during count | 100 | -5 | 95 | 95 | 0 |
| Real shortage | 100 | 0 | 97 | 100 | -3 |
| Receive during count | 100 | +10 | 110 | 110 | 0 |
| Issue after `counted_at` | 100 | 0 | 100 | 100 | 0 |

In the last example, the later issue changes live stock but does not change the
already counted line's variance.

## Manual deployment check

- [ ] Create or select a test item with quantity 100 in warehouse A.
- [ ] Start an inventory for warehouse A and confirm the line snapshot is 100.
- [ ] Receive stock during the active inventory and confirm the operation is
      accepted and visible in the movement journal.
- [ ] Issue stock during the active inventory and confirm the operation is
      accepted and visible in the movement journal.
- [ ] Confirm return, writeoff, and transfer operations also remain available.
- [ ] Enter a physical quantity and confirm `counted_at` is saved.
- [ ] Confirm expected quantity equals the start snapshot plus net movements
      through `counted_at`.
- [ ] Create a movement after `counted_at` and confirm the counted line's
      variance does not change.
- [ ] Cancel a movement made during counting and confirm it is excluded from
      movement delta and expected quantity.
- [ ] Complete a zero-variance inventory and confirm no adjustment movement is
      created.
- [ ] Complete a shortage test and confirm a negative adjustment for exactly
      the shortage is linked to the inventory.
- [ ] Complete a surplus test and confirm a positive adjustment for exactly the
      surplus is linked to the inventory.
- [ ] Confirm stock balances and the movement journal match the posted
      adjustments.
- [ ] Confirm inventory permissions and warehouse access restrictions remain
      unchanged for administrator, storekeeper, and auditor roles.

## Automated smoke coverage

Run the focused workflow checks with:

```bash
python manage.py test core.tests.test_inventory_workflow_smoke
```

The smoke module covers start snapshots, issue and receive reconciliation,
movements after `counted_at`, real shortages and surpluses, transfers,
cancelled movements, and the non-blocking behavior of all normal stock
operations.
