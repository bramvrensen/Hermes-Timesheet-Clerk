# Implementation status

`DESIGN.md` is the functional source of truth. Deployment details live in `DEPLOYMENT.md`.

## 0.6.8 non-destructive persisted Hour Type handling

0.6.8 fixes a second Save-disabled path in the direct mapping editor. A restored entry can already contain a complete persisted direct mapping while the current Simplicate review context fails to re-hydrate the selected service/hour-type relation. The 0.6.7 editor treated that context gap as `hour_type=None`, which silently removed `hour_type_id` from the staged mapping and made `_target_complete()` disable `Save changes`.

The editor now distinguishes existing persisted state from new selectable state:

```text
same selected service + persisted hour_type_id
    + scoped context cannot verify that hour type
        → preserve existing hour type
        → warn that scope is currently unverified
        → keep mapping complete/saveable

service changed
        → do not carry old hour type across
        → require a newly scoped hour type
```

New Hour Type choices remain strictly service-scoped. There is still no global fallback. This is a non-destructive UI rule, not a weakening of the mapping contract: opening the editor may not erase a previously stored booking target because an API/cache/context lookup is incomplete.

Regression coverage verifies both preservation on the same service and rejection of carrying an old hour type to a different service.

## 0.6.7 authoritative project-service hour type scoping

0.6.7 fixes a false-negative in the 0.6.5 Hour type filter. The filter itself was correct, but the review context derived most service/hour-type relationships indirectly from booking assignments. A valid project service without a matching assignment in the selected week could therefore appear to have no valid hour types and disable Save in the review dialog.

Simplicate project services expose their configured hour types directly through the `hour_types[]` collection on `/projects/service`. 0.6.7 preserves that nested collection in `_normalize_service()` and uses it as the primary source of valid service/hour-type pairs.

Evidence priority is now:

```text
project service.hour_types[]   ← authoritative
booking assignment task/hour   ← supplementary
explicit hour-type service_id  ← supplementary
```

Global/unscoped hour types are still never used as a fallback. The change restores valid choices without reopening the unsafe 0.6.4 behaviour where every hour type could be selected for every service.

The persistent review-context cache filename is versioned to `review-context-v067-...`, forcing a fresh Simplicate context fetch after upgrade rather than reusing pre-0.6.7 scoped data for up to 30 minutes.

Regression coverage feeds a realistic project-service payload with nested hour types, including both `id` and `hourtype_id` shapes, and verifies that only those hour types are offered for the selected service.

## 0.6.6 reviewed-entry consolidation and human duration presentation

0.6.6 adds a deterministic post-review consolidation step and removes decimal-hour notation from normal review presentation.

### Reviewed-entry consolidation

`timesheet_clerk.consolidation.consolidate_reviewed_entries()` runs after a human review mutation and after the canonical day reflow.

Two adjacent rows may merge only when all of the following are true:

- same day;
- neither row is ignored or already booked;
- both rows are `RESOLVED`;
- both rows were explicitly human `confirmed` or `corrected`;
- planned end of the first row equals planned start of the second row;
- exact same booking mode and booking target IDs;
- exact same billable state;
- same normalized Clockify description/client/project context.

This allows cases such as two restored Cyclovriend `Reistijd` rows, each one hour and manually mapped to the same travel code, to become one `09:00–11:00` two-hour booking block. It does not merge unrelated work merely because the Simplicate target happens to be the same.

A merged row keeps all underlying `clockify_source_ids`. Canonical Clockify snapshots remain unchanged, so source coverage is preserved and `split_consolidated_entry()` can still reconstruct the individual source rows later.

When consolidation is triggered by editing the second row, that edited `entry_id` is retained as the merged-row ID. This keeps frontend scroll/review feedback stable after save.

### Human duration display

`timesheet_clerk.ui_time.format_duration()` formats presentation time as clock-style human duration instead of decimal hours:

```text
900 s   → 15 min
1800 s  → 30 min
3600 s  → 1u
5400 s  → 1u 30 min
7200 s  → 2u
```

Review cards, Clockify source-duration labels, day summaries, week metrics and target-difference warnings use this formatter. Planned start/end continue to use `HH:MM` ranges. Numeric hour inputs remain numeric controls for efficient editing, but passive time presentation no longer displays values such as `0.25h` or `0.50h`.

## 0.6.5 service-scoped hour type selection

Direct-mapping review treats the Simplicate Task / service as the parent of the Hour type choice. Only scoped hour types are offered, global/unscoped types never act as fallback, and incomplete combinations cannot be saved as resolved direct mappings.

## 0.6.4 review scheduling and frontend performance

The daily booking timeline is generated deterministically with ignored rows excluded, non-billable/internal work first, the first booking at 09:00 and subsequent entries contiguous. Restore without a target reopens as ASK/PENDING. Unknown entries cannot be silently ignored. Simplicate review context is fetched concurrently and cached in shared state.

## 0.6.3 ignored-entry normalization

Ignored rows remain source-covered but intentionally non-bookable and do not require mapping targets.

## 0.6.2 current-week state selection

A historical active week no longer hides generation of a missing current week.

## 0.6.1 removed-source reconciliation

Removed Clockify sources are reconciled from actual plan coverage versus live source IDs; ambiguous partial loss from legacy consolidated entries fails closed.

## 0.6 architecture cleanup

0.6 replaced LLM-authored plan payloads with a decisions-only planner contract. Python owns Clockify source truth, plan identity, revisions, scheduling, review preservation, coverage validation and persistence.

## Update lifecycle

During recovery/development the deterministic fallback remains:

```text
docker exec -i hermes-agent sh -lc '
cd /home/hermes/.hermes/plugins/timesheet-clerk &&
git pull --ff-only &&
grep "^version:" plugin.yaml
' && \
docker restart hermes-agent timesheet-clerk-ui
```

## Remaining write milestone

Simplicate writes remain intentionally disabled pending controlled write validation.
