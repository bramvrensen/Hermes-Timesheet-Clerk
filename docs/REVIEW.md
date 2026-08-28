# Review workflow

## 0.7.14 target-based consolidation

Consolidation follows the final Simplicate booking target, not the Clockify description. Entries on the same day that resolve to the exact same assignment, or to the exact same direct project/service/hour-type/billable signature, are one booking intent and may be consolidated even when different Clockify descriptions or another booking target appeared between them in the original timeline.

AUTO entries are consolidated deterministically during Generate / Refresh scheduling. PROPOSE/ASK entries are only eligible after human confirmation/correction. BOOKED, ignored, skipped or unresolved entries are never consolidated.

All underlying `clockify_source_ids` remain attached to the consolidated row. Distinct Clockify descriptions are joined in the consolidated source description so the eventual Simplicate note remains informative. After consolidation the day is reflowed again from 09:00, preserving the rule that non-billable/internal work precedes billable work.

## 0.7.11 actionable review queue

The original mapping tier (`AUTO`, `PROPOSE`, `ASK`) is audit and learning data. It is not permanently the visual workflow state.

The Review UI treats an entry as pending human review only when it is non-ignored, its original tier is `PROPOSE` or `ASK`, and its `review_state` is not `confirmed`, `corrected` or `skipped`.

Pending entries are shown in an expanded review queue with date/time, Clockify label, original tier and a direct `Review` action that opens the existing entry editor.

After a PROPOSE/ASK entry is confirmed or corrected, the persisted tier is preserved for audit/learning but the card becomes visually neutral with status `READY`. It must no longer remain yellow/red merely because its original model tier was PROPOSE/ASK.

`BOOKED` and `SKIP` continue to take precedence over READY. Only genuinely pending PROPOSE/ASK entries contribute to the review count and block batch booking/approval.

This distinction is intentional:

```text
mapping confidence      workflow state
------------------      --------------
AUTO                    AUTO
PROPOSE + unreviewed    PROPOSE
ASK + unreviewed        ASK
PROPOSE + reviewed      READY
ASK + reviewed          READY
booked                  BOOKED
ignored/skipped         SKIP
```
