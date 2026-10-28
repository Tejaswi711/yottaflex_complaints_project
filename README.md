# Complaint Management - Synthetic Data Generator (YottaFlex AI Round 2)

A small, **standard-library-only Python** project (no pip install needed, Python 3.9+; built on 3.12 and re-tested on 3.11 with identical checksums)
that generates a linked, rule-driven synthetic dataset for this workflow:

> classify complaints -> assign owners -> enforce SLAs -> track resolution and customer communication

It produces 15 related tables, a **separate ground-truth file** with labelled anomalies, SQL seed data, a data
dictionary, a validation report and an evaluation report. Everything comes from one fixed seed (`20261022`).

## Quick start

```bash
python generate_data.py                 # full data: 5,000 customers / 8,000 orders / 2,000 complaints / 6,000 messages
python validate_data.py                 # 15+ groups of checks + anomaly detection vs ground truth -> PASS
python evaluate.py                      # classifier accuracy + SLA / escalation / CSAT metrics
python check_reproducibility.py         # generates twice, compares row counts + SHA-256 checksums

# smaller "starter" dataset, same generator:
python generate_data.py --customers 500 --orders 800 --complaints 200 --messages 600 --out starter
python validate_data.py --out starter
```

Generator command used for the committed `output/` folder: `python generate_data.py --out output`

## Folder layout

| Path | What it is |
|---|---|
| `generate_data.py` | The generator (all business logic) |
| `rules.py` | Priority engine, allowed status transitions, shared constants |
| `schema_spec.py` | Table/field definitions - also builds `schema.sql` and the data dictionary |
| `validate_data.py`, `evaluate.py`, `check_reproducibility.py` | Verification tools |
| `output/data/*.csv` | The 15 tables (model **inputs**) |
| `output/ground_truth/ground_truth.csv` | Correct labels + injected anomalies (**never an input feature**) |
| `output/sql/schema.sql`, `seed.sql` | SQLite-compatible schema and INSERT seed data |
| `output/docs/data_dictionary.md` | Every field: type, required, allowed values, uniqueness, validation rule |
| `output/manifest.json` | Seed, parameters, row counts, SHA-256 of every file, source manifest |
| `output/validation_summary.json`, `evaluation_report.json`, `reproducibility_report.json` | Results |
| `PROMPT_HISTORY.md`, `AI_USAGE.md` | AI-use disclosure |

## Data model

```
Customer 1--N Order N--M Product        (bridge table: order_items)
Customer 1--N Complaint N--1 Order, N--1 Product, N--1 Category, N--1 PriorityLevel
Complaint 1--N complaint_status_events   (append-only history)
Complaint 1--N complaint_messages        (customer communication)
Complaint 1--N assignments --N:1 Agent   (ownership history)
Complaint 1--1 sla_clocks
Complaint 1--0..1 resolutions
Complaint 1--0..1 surveys
Complaint 0..1 --> Complaint             (repeat_of_complaint_id)
PriorityRule / PriorityLevel             (reference data applied by the rules engine)
```

IDs follow the required patterns: `CUS-000001`, `ORD-2026-000001`, `CMP-2026-000001`, `MSG-<complaint-id>-001`,
`SLA-<complaint-id>`, `RES-<complaint-id>` (plus `EVT-`, `ASG-`, `SVY-` for the extra tables).
Full field-level details: `output/docs/data_dictionary.md`.

## Business rules (all in code, none random "labels")

1. **Parents first:** customers, products -> orders + order_items -> complaints -> events, assignments, SLA, resolution, survey, messages.
2. **Classify:** a keyword classifier reads the customer's first message and picks 1 of 10 categories (default: Poor Service).
   ~8% of messages are deliberately vague, so the classifier makes realistic mistakes. Severity = category default.
3. **Sentiment:** word-lexicon score from -1 to 1 on the same message.
4. **Priority** (`priority_rules.csv` + `priority_levels.csv`): product-safety forces **P1**; otherwise rule points are added
   (angry sentiment, order value >= 5,000 / 20,000, repeat +2, vulnerable +2, High severity +1) and the level is picked by points
   (P1 >= 6, P2 >= 4, P3 >= 2, else P4).
5. **Repeat:** same customer + product + category within 30 days of an earlier complaint -> `repeat_of_complaint_id` points at it.
6. **Assign:** team from the category (safety -> Safety & Compliance), queue from the priority level (P1-URGENT ... P4-LOW).
7. **SLA:** P1 24h, P2 72h, P3 120h, P4 240h. `deadline = created + SLA hours + time spent WAITING_CUSTOMER`
   (the clock is paused only while waiting for the customer).
8. **Escalation:** when *working time* passes 75% of the SLA, an `ESCALATED` event is added and a new assignment goes to the Escalations team.
9. **Lifecycle:** `NEW -> ASSIGNED -> IN_PROGRESS -> (WAITING_CUSTOMER) -> (ESCALATED) -> RESOLVED -> CLOSED -> (REOPENED -> ... -> CLOSED)`.
   About 8% of complaints are reopened; every change is a new row, nothing is overwritten.
10. **Derived values** (order totals, status, SLA deadline/paused hours/breach flag, resolution times, reopen count, repeat flag, CSAT) are
    calculated from source records. Events after the data cut-off (`2026-10-22 23:59`) are dropped, so a few complaints are still open.
11. **Boundary cases:** ~2% of complaints resolve exactly on the SLA deadline and ~2% exactly at the escalation threshold.

## Injected anomalies (labelled in `ground_truth.csv`, 10 each at full size, 2 each at starter size)

| issue_type | What is broken |
|---|---|
| COMPLAINT_WITHOUT_CUSTOMER | `customer_id` blank |
| RESOLUTION_BEFORE_COMPLAINT | resolution time earlier than the complaint |
| SLA_CLOCK_PAUSES_INCORRECTLY | paused hours do not match WAITING_CUSTOMER time |
| REPEAT_NOT_LINKED | repeat complaint without `repeat_of_complaint_id` |
| CRITICAL_SAFETY_LOW_PRIORITY_QUEUE | safety complaint put in Customer Care / P4-LOW |
| SURVEY_BEFORE_CLOSURE | survey sent before the CLOSED event |

Each anomaly touches exactly one complaint's records; all other rows stay valid. Baseline data is generated clean first, then anomalies are injected.

## Results (full dataset, seed 20261022)

- **Validation: PASS.** 0 key/enum/join/arithmetic failures. All 60 injected anomalies were caught and **0** clean complaints were flagged.
- **Reproducibility:** two runs gave identical row counts and identical SHA-256 checksums for all 18 data files (also independent of `PYTHONHASHSEED`).
- **Classifier vs ground truth:** category accuracy 93.0%, priority accuracy 97.8%, safety recall 100%.
- **Operations:** priority mix P1 4.0% / P2 7.7% / P3 35.8% / P4 52.6%; overall SLA breach 8.0%; escalation 19-38% by priority;
  repeat 8.0%; reopened 8.3%; mean first resolution 108.7 h; mean CSAT 3.83.

How I know it works: `validate_data.py` recomputes priority, SLA deadlines, pauses, escalations, repeat links, resolution/status reconciliation
and ownership chains from the CSVs alone, then compares what it flagged with the ground truth. I also corrupted one order total on purpose
and confirmed the validator reports FAIL.

## Assumptions and limitations

- All money is INR. Names, e-mails (`@example.test`) and the vulnerable flag are synthetic. No external or public data is used (see `manifest.json`), so there are no licence or personal-data issues.
- One SLA clock per complaint; the second cycle of a reopened complaint has no new SLA.
- Escalated complaints never have a customer-wait pause (keeps the pause/escalation timeline simple).
- The classifier is a simple keyword matcher, not an ML model; its errors are the "realistic noise" measured in `evaluate.py`.
- `seed.sql` contains the injected anomalies on purpose. Load it **without** `PRAGMA foreign_keys=ON`, otherwise the 10 blank-customer complaints are rejected.
- Timestamps have no time zone. Checksums matched on Python 3.12 and 3.11; other versions are not tested.
- Most complaints are already closed at the cut-off (about 1.5% are open), because complaints are spread over ~9 months.
- Table `complaints` does not store the complaint text; it is the first row of `complaint_messages` (kind `CUSTOMER_COMPLAINT`).

## Requirement checklist

| Requirement | Where |
|---|---|
| Data dictionary (Step 1) | `output/docs/data_dictionary.md` |
| Parent tables first, deterministic IDs (Steps 2-3) | `generate_data.py`, ID patterns above |
| Volume, 10 categories, 4 priority levels, repeat / vulnerable / safety / missing order / refund pending / reopened (Step 4) | `manifest.json`, `categories.csv`, `priority_levels.csv`, `resolutions.csv` (`refund_status`) |
| Labelled edge cases (Step 5) | injected anomalies table |
| Derived values (Step 6) | rule 10 |
| Separate ground truth (Step 7) | `output/ground_truth/ground_truth.csv` |
| Validation (Step 8) | `validate_data.py`, `validation_summary.json` |
| CSV / SQL export, manifest (Step 9) | `output/data`, `output/sql`, `manifest.json` |
| Reproducibility (Step 10) | `check_reproducibility.py`, `reproducibility_report.json` |

## AI Use

AI tools were used for requirement clarification, technical guidance, troubleshooting, and reviewing validation and evaluation approaches.
