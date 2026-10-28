#!/usr/bin/env python3
"""Validate a generated dataset (standard library only).

    python validate_data.py --out output

Part 1: general checks (keys, joins, enums, dates, arithmetic, lifecycle, rules).
Part 2: compare what the checks flagged with ground_truth.csv.
Expected result: every injected anomaly is caught and nothing else is flagged.
"""
import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import timedelta

import rules as R
import schema_spec

ENUMS = {
    ("customers", "segment"): {"Standard", "Premium", "VIP"},
    ("orders", "delivery_status"): {"DELIVERED", "LATE", "LOST"},
    ("orders", "order_channel"): {"Web", "Mobile App", "Marketplace"},
    ("categories", "default_severity"): set(R.SEVERITY_RANK),
    ("complaints", "channel"): {"Email", "Phone", "Web Form", "Mobile App", "Social Media", "Chat"},
    ("complaints", "severity"): set(R.SEVERITY_RANK),
    ("complaints", "priority_level"): {"P1", "P2", "P3", "P4"},
    ("complaints", "current_status"): {s for s in R.TRANSITIONS if s} | {"ASSIGNED"},
    ("complaint_status_events", "actor_type"): {"SYSTEM", "AGENT", "CUSTOMER"},
    ("complaint_messages", "sender_type"): {"CUSTOMER", "AGENT", "SYSTEM"},
    ("assignments", "reason"): {"INITIAL", "ESCALATION", "REOPEN"},
    ("assignments", "queue"): {"P1-URGENT", "P2-HIGH", "P3-STANDARD", "P4-LOW", "ESCALATION"},
    ("resolutions", "resolution_type"): {"REFUND", "REPLACEMENT", "REPAIR", "CREDIT", "APOLOGY_EXPLANATION"},
    ("resolutions", "refund_status"): {"NOT_APPLICABLE", "PENDING", "PAID"},
}
BOOLS = [("customers", "vulnerable_flag"), ("products", "is_hazard_prone"), ("complaints", "is_safety_issue"),
         ("complaints", "is_repeat"), ("complaints", "vulnerable_flag"), ("sla_clocks", "is_breached"),
         ("assignments", "is_current")]

# check name -> injected issue type it is expected to catch
EXPECTED_CHECK = {
    "COMPLAINT_WITHOUT_CUSTOMER": "complaint_without_customer",
    "RESOLUTION_BEFORE_COMPLAINT": "resolution_before_complaint",
    "SLA_CLOCK_PAUSES_INCORRECTLY": "sla_pause_mismatch",
    "REPEAT_NOT_LINKED": "repeat_not_linked",
    "CRITICAL_SAFETY_LOW_PRIORITY_QUEUE": "safety_low_queue",
    "SURVEY_BEFORE_CLOSURE": "survey_before_closure",
}


def load(folder):
    data = {}
    for name in schema_spec.TABLES:
        with open(os.path.join(folder, "data", f"{name}.csv"), newline="", encoding="utf-8") as fh:
            data[name] = list(csv.DictReader(fh))
    return data


def group(rows, key):
    out = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    d = load(args.out)

    general = Counter()               # failures that are never expected (not complaint specific)
    flagged = defaultdict(set)        # check name -> complaint ids
    totals = Counter()                # rows examined per check group (for the report)

    # ---- 1. primary keys
    for name, spec in schema_spec.TABLES.items():
        keys = [tuple(r[c] for c in spec["pk"]) for r in d[name]]
        general[f"pk_duplicate:{name}"] += len(keys) - len(set(keys))
        for u in spec["unique"]:
            vals = [r[u] for r in d[name]]
            general[f"unique_duplicate:{name}.{u}"] += len(vals) - len(set(vals))
        for f in spec["fields"]:
            if f[2] == "Y" and name != "complaints":
                general[f"required_blank:{name}.{f[0]}"] += sum(1 for r in d[name] if r[f[0]] == "")

    # ---- 2. foreign keys
    pk_sets = {n: {r[schema_spec.TABLES[n]["pk"][0]] for r in d[n]} for n in d}
    for name, spec in schema_spec.TABLES.items():
        for col, parent, pcol in spec["fks"]:
            valid = pk_sets[parent]
            for r in d[name]:
                v = r[col]
                if v == "" and (name, col) == ("complaints", "repeat_of_complaint_id"):
                    continue
                if v not in valid:
                    if (name, col) == ("complaints", "customer_id"):
                        flagged["complaint_without_customer"].add(r["complaint_id"])
                    else:
                        general[f"fk_broken:{name}.{col}"] += 1
    order_items = {(i["order_id"], i["product_id"]) for i in d["order_items"]}
    for c in d["complaints"]:
        if (c["order_id"], c["product_id"]) not in order_items:
            general["fk_broken:complaints.product_not_in_order"] += 1

    # ---- 3. enums and booleans
    for (t, col), allowed in ENUMS.items():
        general[f"enum_invalid:{t}.{col}"] += sum(1 for r in d[t] if r[col] not in allowed)
    for t, col in BOOLS:
        general[f"bool_invalid:{t}.{col}"] += sum(1 for r in d[t] if r[col] not in ("0", "1"))

    # ---- 4. arithmetic
    items_by_order = group(d["order_items"], "order_id")
    order_total = {o["order_id"]: float(o["order_total"]) for o in d["orders"]}
    for oid, lines in items_by_order.items():
        if abs(sum(float(l["line_total"]) for l in lines) - order_total[oid]) > 0.01:
            general["arith:order_total_vs_items"] += 1
        for l in lines:
            if abs(int(l["quantity"]) * float(l["unit_price"]) - float(l["line_total"])) > 0.01:
                general["arith:line_total"] += 1
    for o in d["orders"]:
        late = o["delivered_date"] != "" and o["delivered_date"] > o["promised_date"]
        want = "LOST" if o["delivered_date"] == "" else ("LATE" if late else "DELIVERED")
        if want != o["delivery_status"]:
            general["derived:order_delivery_status"] += 1
    cust = {c["customer_id"]: c for c in d["customers"]}
    cat_team = {c["category_id"]: c["owning_team"] for c in d["categories"]}
    levels = d["priority_levels"]
    level_by = {l["priority_level"]: l for l in levels}
    rules = d["priority_rules"]

    events = group(d["complaint_status_events"], "complaint_id")
    msgs = group(d["complaint_messages"], "complaint_id")
    asgs = group(d["assignments"], "complaint_id")
    slas = {s["complaint_id"]: s for s in d["sla_clocks"]}
    ress = {r["complaint_id"]: r for r in d["resolutions"]}
    survs = {s["complaint_id"]: s for s in d["surveys"]}
    as_of = R.AS_OF

    # ---- 5. repeat rule
    last = {}
    for c in sorted(d["complaints"], key=lambda c: (c["created_at"], c["complaint_id"])):
        if c["customer_id"] == "":
            continue
        key = (c["customer_id"], c["product_id"], c["category_id"])
        prev = last.get(key)
        expected = prev[1] if prev and R.parse_ts(c["created_at"]) - prev[0] <= timedelta(days=R.REPEAT_WINDOW_DAYS) else ""
        stored = c["repeat_of_complaint_id"]
        if expected and not stored:
            flagged["repeat_not_linked"].add(c["complaint_id"])
        elif expected != stored:
            flagged["repeat_link_wrong"].add(c["complaint_id"])
        if int(c["is_repeat"]) != int(stored != ""):
            flagged["repeat_flag_mismatch"].add(c["complaint_id"])
        last[key] = (R.parse_ts(c["created_at"]), c["complaint_id"])

    # ---- 6. per complaint checks
    dup_seen = set()
    for c in d["complaints"]:
        cid = c["complaint_id"]
        created = R.parse_ts(c["created_at"])
        if created > as_of:
            general["date:complaint_after_cutoff"] += 1
        if c["customer_id"] in cust:
            if cust[c["customer_id"]]["vulnerable_flag"] != c["vulnerable_flag"]:
                flagged["vulnerable_snapshot_mismatch"].add(cid)
        if abs(float(c["order_value"]) - order_total.get(c["order_id"], -1)) > 0.01:
            flagged["order_value_mismatch"].add(cid)
        key = (c["customer_id"], c["order_id"], c["product_id"], c["category_id"], c["created_at"])
        if key in dup_seen:
            flagged["duplicate_complaint"].add(cid)
        dup_seen.add(key)

        # priority reproducible from rules
        if R.compute_priority(rules, levels, R.priority_facts(c)) != c["priority_level"]:
            flagged["priority_mismatch"].add(cid)
        level = level_by[c["priority_level"]]
        sla_min = int(level["sla_hours"]) * 60
        esc_min = int(sla_min * float(level["escalation_pct"]))

        # lifecycle
        ev = sorted(events[cid], key=lambda e: e["event_id"])
        if not ev or ev[0]["to_status"] != "NEW" or ev[0]["event_time"] != c["created_at"]:
            flagged["lifecycle_start"].add(cid)
            continue
        prev_status, prev_time = None, None
        for e in ev:
            t = R.parse_ts(e["event_time"])
            if e["from_status"] != (prev_status or "") or e["to_status"] not in R.TRANSITIONS.get(prev_status, set()):
                flagged["lifecycle_transition"].add(cid)
            if prev_time and t < prev_time:
                flagged["lifecycle_time_order"].add(cid)
            if t > as_of:
                flagged["lifecycle_after_cutoff"].add(cid)
            prev_status, prev_time = e["to_status"], t
        if c["current_status"] != ev[-1]["to_status"]:
            flagged["status_vs_events_mismatch"].add(cid)
        pairs = [(e["to_status"], R.parse_ts(e["event_time"])) for e in ev]

        # SLA clock: pauses must equal time spent WAITING_CUSTOMER
        paused = 0
        pause_segments = []
        for i, (s, t) in enumerate(pairs):
            if s == "WAITING_CUSTOMER":
                end = pairs[i + 1][1] if i + 1 < len(pairs) else as_of
                paused += int((end - t).total_seconds() // 60)
                pause_segments.append((t, end))
        sla = slas.get(cid)
        if sla is None:
            flagged["sla_missing"].add(cid)
        else:
            if abs(float(sla["paused_hours"]) - round(paused / 60, 2)) > 0.011 or \
               int(sla["pause_count"]) != sum(1 for s, _ in pairs if s == "WAITING_CUSTOMER"):
                flagged["sla_pause_mismatch"].add(cid)
            if sla["priority_level"] != c["priority_level"] or int(sla["sla_hours"]) != int(level["sla_hours"]) \
               or sla["started_at"] != c["created_at"]:
                flagged["sla_header_mismatch"].add(cid)
            deadline = created + timedelta(minutes=sla_min + float(sla["paused_hours"]) * 60)
            if abs((R.parse_ts(sla["deadline_at"]) - deadline).total_seconds()) > 60:
                flagged["sla_deadline_mismatch"].add(cid)
            stopped = R.parse_ts(sla["stopped_at"]) if sla["stopped_at"] else None
            if int(sla["is_breached"]) != int((stopped or as_of) > R.parse_ts(sla["deadline_at"])):
                flagged["sla_breach_flag_mismatch"].add(cid)
            first_res = next((t for s, t in pairs if s == "RESOLVED"), None)
            if (first_res and sla["stopped_at"] != R.ts(first_res)) or (not first_res and sla["stopped_at"]):
                flagged["sla_stop_mismatch"].add(cid)

        # escalation happens at the threshold (working time = elapsed - paused)
        first_res = next((t for s, t in pairs if s == "RESOLVED"), None)
        end = first_res or as_of

        def working(until):
            wait = sum(int((min(b, until) - a).total_seconds() // 60) for a, b in pause_segments if a < until)
            return int((until - created).total_seconds() // 60) - wait
        esc = [t for s, t in pairs if s == "ESCALATED"]
        w_end = working(end)
        if (esc and w_end < esc_min - 1) or (not esc and w_end > esc_min + 1):
            flagged["escalation_threshold_wrong"].add(cid)
        for t in esc:
            if abs(working(t) - esc_min) > 1:
                flagged["escalation_timing_wrong"].add(cid)

        # reopened complaints keep their history
        n_reopen = sum(1 for s, _ in pairs if s == "REOPENED")
        if n_reopen:
            before = [s for s, _ in pairs[:[s for s, _ in pairs].index("REOPENED")]]
            if not {"NEW", "RESOLVED", "CLOSED"} <= set(before):
                flagged["reopen_history_lost"].add(cid)
            if not any(a["reason"] == "REOPEN" for a in asgs[cid]) or asgs[cid][0]["reason"] != "INITIAL":
                flagged["reopen_history_lost"].add(cid)

        # resolution reconciles with status events
        res = ress.get(cid)
        res_times = [t for s, t in pairs if s == "RESOLVED"]
        if res_times and not res:
            flagged["resolution_missing"].add(cid)
        if res and not res_times:
            flagged["resolution_event_mismatch"].add(cid)
        if res and res_times:
            if res["first_resolved_at"] != R.ts(res_times[0]) or res["resolved_at"] != R.ts(res_times[-1]) \
               or int(res["reopen_count"]) != n_reopen:
                flagged["resolution_event_mismatch"].add(cid)
            if R.parse_ts(res["first_resolved_at"]) < created:
                flagged["resolution_before_complaint"].add(cid)
            if res["resolution_type"] != "REFUND" and res["refund_status"] == "PENDING":
                flagged["refund_status_mismatch"].add(cid)

        # survey only after final closure
        sv = survs.get(cid)
        closes = [t for s, t in pairs if s == "CLOSED"]
        if sv:
            if not closes or pairs[-1][0] != "CLOSED":
                flagged["survey_without_closure"].add(cid)
            elif R.parse_ts(sv["sent_at"]) < closes[-1]:
                flagged["survey_before_closure"].add(cid)
            if sv["responded_at"] and R.parse_ts(sv["responded_at"]) < R.parse_ts(sv["sent_at"]):
                flagged["survey_response_before_sent"].add(cid)
            if (sv["csat_score"] == "") != (sv["responded_at"] == ""):
                flagged["survey_score_mismatch"].add(cid)

        # ownership history
        a_list = sorted(asgs[cid], key=lambda a: a["assignment_id"])
        if any(e["to_status"] == "ASSIGNED" for e in ev):
            if sum(a["is_current"] == "1" for a in a_list) != 1 or a_list[-1]["ended_at"] != "":
                flagged["ownership_current_wrong"].add(cid)
            for x, y in zip(a_list, a_list[1:]):
                if x["ended_at"] != y["assigned_at"]:
                    flagged["ownership_gap"].add(cid)
            want_team = "Safety & Compliance" if c["is_safety_issue"] == "1" else cat_team[c["category_id"]]
            first = a_list[0]
            if first["queue"] != level["queue"] or first["team"] != want_team:
                flagged["safety_low_queue" if c["is_safety_issue"] == "1" else "assignment_rule_mismatch"].add(cid)
            if (len(esc) > 0) != any(a["reason"] == "ESCALATION" for a in a_list):
                flagged["escalation_assignment_missing"].add(cid)
        elif a_list:
            flagged["assignment_without_event"].add(cid)

        # messages
        m_list = sorted(msgs[cid], key=lambda m: m["message_id"])
        if not m_list or m_list[0]["message_kind"] != "CUSTOMER_COMPLAINT" or m_list[0]["sent_at"] != c["created_at"]:
            flagged["message_first_wrong"].add(cid)
        for n, m in enumerate(m_list, 1):
            if m["message_id"] != f"MSG-{cid}-{n:03d}" or R.parse_ts(m["sent_at"]) < created or R.parse_ts(m["sent_at"]) > as_of:
                flagged["message_sequence_wrong"].add(cid)
            if n > 1 and m["sent_at"] < m_list[n - 2]["sent_at"]:
                flagged["message_sequence_wrong"].add(cid)

    # ---- 7. report
    gt_path = os.path.join(args.out, "ground_truth", "ground_truth.csv")
    with open(gt_path, newline="", encoding="utf-8") as fh:
        truth = {r["complaint_id"]: r for r in csv.DictReader(fh)}
    injected = {cid: r["issue_type"] for cid, r in truth.items() if r["issue_type"]}
    all_flagged = set().union(*flagged.values()) if flagged else set()
    general_failures = {k: v for k, v in general.items() if v}

    matrix = {}
    for issue, check in EXPECTED_CHECK.items():
        ids = {cid for cid, t in injected.items() if t == issue}
        caught = ids & flagged.get(check, set())
        matrix[issue] = {"injected": len(ids), "caught": len(caught),
                         "extra_flags_for_same_check": len(flagged.get(check, set()) - ids)}
    missed = [cid for cid, t in injected.items() if cid not in flagged.get(EXPECTED_CHECK[t], set())]
    unexpected = sorted(all_flagged - set(injected))
    ok = not general_failures and not missed and not unexpected

    summary = {
        "result": "PASS" if ok else "FAIL",
        "rows": {n: len(d[n]) for n in d},
        "general_failures": general_failures,
        "flags_by_check": {k: len(v) for k, v in sorted(flagged.items())},
        "anomaly_detection": matrix,
        "missed_anomalies": missed,
        "unexpected_flags": unexpected[:20],
        "unexpected_flag_count": len(unexpected),
    }
    with open(os.path.join(args.out, "validation_summary.json"), "w", newline="\n") as fh:
        json.dump(summary, fh, indent=2)
        fh.write("\n")

    print("VALIDATION", summary["result"])
    print(f"  general checks (keys, enums, arithmetic, joins): {sum(general_failures.values())} failures")
    for k, v in general_failures.items():
        print("    ", k, v)
    print("  injected anomaly detection:")
    for issue, m in matrix.items():
        print(f"    {issue:38s} injected={m['injected']:>3}  caught={m['caught']:>3}")
    print(f"  missed anomalies: {len(missed)}   unexpected flags on clean complaints: {len(unexpected)}")
    if unexpected:
        by_check = {k: len(v - set(injected)) for k, v in flagged.items() if v - set(injected)}
        print("    unexpected by check:", by_check)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
