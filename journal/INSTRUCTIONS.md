# Journal Instructions: Causal Chain Preservation

## Purpose

This journal exists to prevent **causal amnesia** — the failure mode where a future session can see that the system is in state C, but has no record of why A led to B led to C, and must re-derive root causes from scratch. Every hour spent re-discovering a known root cause is evidence that a prior session documented events without documenting their causes.

The goal is not a log of what happened. It is a **navigable causal record** of why the system is in its current state.

---

## The Core Principle

Document causes, not events.

- **Event:** "Fixed the store-sync orphan detection bug."
- **Cause:** "store-sync was matching store docs as canonical if their display_name matched any known file ID, without verifying the full doc suffix matched the DB-recorded gemini_store_doc_id. This silently approved duplicate store documents. Fixed by adding get_canonical_file_id_to_store_doc_map() and requiring exact two-field match."

The second form makes the current state navigable. If a future session sees orphan detection behavior that seems wrong, the causal record tells them what the previous wrong behavior was, why it was wrong, and what the correct invariant is — without re-investigating.

---

## When to Write

Write a journal entry at the close of:
- Any session that changes system state in a non-obvious way
- Any session that discovers a root cause (not just fixes a symptom)
- Any session that makes a tolerance or policy decision
- Any session where you ran into a surprise — something that required investigation to understand

A session that only executes a predefined plan with no surprises may need only a short "completed X, state is Y" note. A session with investigation, discovery, or decisions needs a full causal entry.

---

## Entry Format

Each entry lives in a file named `journal/YYYY-MM-DD.md`. If multiple significant sessions occur in one day, use a single file with clearly labeled sections.

### Required Sections

**1. Overview (2–5 sentences)**

What was the starting point and what was achieved? Name the session's net result in terms of system state, not just tasks completed.

*Example: "A full-day session that began at a plan checkpoint, uncovered a systemic retrieval failure across 1,749 files, executed a 7.5-hour production remediation, and ended with two independent STABLE verdicts."*

**2. Starting Point**

What state was the system in when the session began? What was expected? What was the first action? This allows a future reader to understand the context the discoveries were made in — not just what was found.

**3. Root Cause Analysis (for each non-obvious discovery)**

For each thing that required investigation to understand, document:

- **What was observed:** The symptom or unexpected state
- **What was expected:** What the correct behavior should have been
- **The causal chain:** Why A caused B caused C — not just "A was wrong"
- **What the correct invariant is:** The rule that, if followed, would have prevented the problem

*Example: "store-sync reported 0 orphans despite the stability check finding 1 orphan. Investigation: store-sync was classifying a doc as canonical if display_name matched any known file_id, without checking the doc suffix. This meant a duplicate store document (pm7yaaavyz4d-x752bhm52hlm) for a file whose canonical doc was pm7yaaavyz4d-dyf6iovztwfz was silently passed as canonical. The correct invariant: a store doc is canonical only if both its display_name matches a known file_id AND its doc suffix matches the gemini_store_doc_id recorded in the DB for that file."*

**4. Decisions Made**

For each non-trivial decision (a policy choice, a tolerance level, an exclusion, an approach selection):

- **What was decided:** The specific choice
- **Why this option and not the alternatives:** Name at least one rejected alternative and why it was rejected
- **What future sessions should NOT re-litigate:** If this decision is stable, say so explicitly

*Example: "A7 tolerance raised to 2 (not 0). Rejected: tolerance=0 with per-file manual exclusions — this hides the structural limitation rather than acknowledging it. Accepted: tolerance=2 with Office Hour files excluded by category — these files are structurally indistinguishable to semantic search (44 files in a series, class number is the only discriminating signal). Future sessions should not attempt to achieve tolerance=0 without a fundamental change to how these series are uploaded or queried."*

**5. Current State (at close of session)**

A precise snapshot of the system's state at the end of the session. For each non-obvious property, name its cause.

Format as a table when possible:

| Property | Value | Cause |
|----------|-------|-------|
| DB indexed | 1,749 | Full library uploaded |
| A7 tolerance | 2 | Large numbered series have inherent ~2% failure rate at semantic search |
| Office Hour files excluded | 60 | No discriminating metadata beyond class number; same rationale as Episodes |
| Identity headers present | 1,749/1,749 | Systemic re-upload via re_enrich_retrieval.py (2026-02-25) |

**6. Files Changed**

List every file modified and the nature of the change. This is a quick navigation aid — not a substitute for the root cause documentation above.

**7. Lessons Learned**

What did this session confirm or discover about the system's architecture, its failure modes, or the tools used? Write these as stable facts, not session observations.

*Example: "The re_enrich_retrieval.py upload-first sequence accumulates orphaned store docs by design. Every bulk re-upload should be followed immediately by store-sync --no-dry-run to clear the stale old docs."*

---

## Anti-Amnesia Checklist

Before closing an entry, ask:

1. **If I lose all memory of this session, will a future reader know WHY the system is in each non-obvious state?** Go through each non-obvious property in Current State. If the cause column is empty or vague, fill it in.

2. **Did I document the decision tree, not just the final branches?** For each decision, have I named what alternatives were considered and rejected? "We chose X" without "instead of Y, because Z" is incomplete.

3. **Are there any implicit assumptions a future session might violate?** Name them explicitly. "Do not run --reset-existing without immediately running store-sync --no-dry-run after" is the kind of constraint that a future session will violate if it's not documented.

4. **Is there anything I re-discovered today that was already documented somewhere?** If yes, update the prior documentation (MEMORY.md, STATE.md) rather than just noting it in the journal. The journal is not the authoritative source for stable facts — it's the causal record of how those facts were discovered.

5. **What would a fresh session need to know first to understand what's here?** Order the entry so that context precedes discoveries, discoveries precede decisions, and decisions precede current state. A future reader will read top to bottom.

---

## What the Journal Is NOT

- **Not a task log.** "Completed X, Y, Z" without causes is not useful.
- **Not a replacement for MEMORY.md.** Stable patterns and confirmed invariants go in MEMORY.md. The journal records how they were discovered.
- **Not a replacement for STATE.md.** Current position and blockers go in STATE.md. The journal records the causal chain that produced that position.
- **Not retrospective event summary.** If you find yourself writing "and then we did X, and then we did Y," you are writing events, not causes.

---

## Example Entry Structure

```markdown
# Journal — YYYY-MM-DD

## Overview
One paragraph: what state was the system in when we started, what happened,
what state is it in now. Focus on net result, not chronology.

## Starting Point
What was expected before the session began. What was the first action.

## Root Cause Analysis

### [Specific Problem 1]: [Short Name]
**Observed:** ...
**Expected:** ...
**Causal chain:** ...
**Correct invariant:** ...

### [Specific Problem 2]: [Short Name]
...

## Decisions Made

### [Decision 1]: [Short Name]
**Decision:** ...
**Rejected alternatives:** ...
**Stable:** [yes/no — should this be re-evaluated?]

## Current State

| Property | Value | Cause |
|----------|-------|-------|
| ... | ... | ... |

## Files Changed

| File | Change |
|------|--------|
| ... | ... |

## Lessons Learned
- ...
- ...
```

---

## Why This Format

This format was designed to prevent a specific failure mode observed on 2026-02-25: a stability check returned UNSTABLE, and the session required hours of investigation to discover that (a) store-sync had a looser-than-correct orphan detection rule and (b) 1,746 of 1,749 indexed files lacked identity headers because a remediation script had never been run. Both of these were discoverable from prior commits and documentation, but the causal chain — why these properties were true — was not pre-documented in a navigable form. The result was re-derivation from scratch of root causes that had already been found.

The format above is specifically structured to prevent that failure mode: every non-obvious system property must be accompanied by its cause, every decision must include its rejected alternatives, and every lesson learned must be written as a stable fact rather than a session observation.
