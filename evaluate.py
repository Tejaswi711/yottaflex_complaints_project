#!/usr/bin/env python3
"""Measurable outputs: classifier quality vs ground truth + operational KPIs.

    python evaluate.py --out output
"""
import argparse
import csv
import json
import os
from collections import Counter, defaultdict
from statistics import mean

import rules as R


def read(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def pct(a, b):
    return round(100.0 * a / b, 1) if b else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    data = lambda n: read(os.path.join(args.out, "data", f"{n}.csv"))
    complaints, slas, ress, survs = data("complaints"), data("sla_clocks"), data("resolutions"), data("surveys")
    msgs, events = data("complaint_messages"), data("complaint_status_events")
    truth = {r["complaint_id"]: r for r in read(os.path.join(args.out, "ground_truth", "ground_truth.csv"))}
    names = {c["category_id"]: c["category_name"] for c in data("categories")}

    # ---- 1. how good were the system decisions compared with ground truth?
    n = len(complaints)
    cat_ok = sum(c["category_id"] == truth[c["complaint_id"]]["true_category_id"] for c in complaints)
    pri_ok = sum(c["priority_level"] == truth[c["complaint_id"]]["expected_priority_level"] for c in complaints)
    per_cat = {}
    for cat, name in names.items():
        tp = sum(c["category_id"] == cat and truth[c["complaint_id"]]["true_category_id"] == cat for c in complaints)
        pred = sum(c["category_id"] == cat for c in complaints)
        actual = sum(t["true_category_id"] == cat for t in truth.values())
        per_cat[name] = {"precision_pct": pct(tp, pred), "recall_pct": pct(tp, actual), "support": actual}
    safety_true = [c for c in complaints if truth[c["complaint_id"]]["true_category_id"] == "CAT-06"]
    safety_found = sum(c["is_safety_issue"] == "1" for c in safety_true)
    classification = {"category_accuracy_pct": pct(cat_ok, n), "priority_accuracy_pct": pct(pri_ok, n),
                      "safety_recall_pct": pct(safety_found, len(safety_true)), "per_category": per_cat}

    # ---- 2. operational KPIs
    sla_by = {s["complaint_id"]: s for s in slas}
    by_pri = defaultdict(list)
    for c in complaints:
        by_pri[c["priority_level"]].append(sla_by[c["complaint_id"]])
    sla_table = {}
    for p in sorted(by_pri):
        rows = by_pri[p]
        sla_table[p] = {"complaints": len(rows), "breach_rate_pct": pct(sum(r["is_breached"] == "1" for r in rows), len(rows)),
                        "escalation_rate_pct": pct(sum(r["escalated_at"] != "" for r in rows), len(rows))}
    created = {c["complaint_id"]: R.parse_ts(c["created_at"]) for c in complaints}
    hours = [(R.parse_ts(r["first_resolved_at"]) - created[r["complaint_id"]]).total_seconds() / 3600
             for r in ress if R.parse_ts(r["first_resolved_at"]) >= created[r["complaint_id"]]]
    scores = [int(s["csat_score"]) for s in survs if s["csat_score"]]
    kpis = {
        "complaints": n,
        "status_mix": dict(Counter(c["current_status"] for c in complaints)),
        "priority_mix_pct": {p: pct(v, n) for p, v in sorted(Counter(c["priority_level"] for c in complaints).items())},
        "repeat_rate_pct": pct(sum(c["is_repeat"] == "1" for c in complaints), n),
        "vulnerable_rate_pct": pct(sum(c["vulnerable_flag"] == "1" for c in complaints), n),
        "reopen_rate_pct": pct(sum(int(r["reopen_count"]) > 0 for r in ress), len(ress)),
        "overall_breach_rate_pct": pct(sum(s["is_breached"] == "1" for s in slas), len(slas)),
        "mean_hours_to_first_resolution": round(mean(hours), 1) if hours else None,
        "refund_pending": sum(r["refund_status"] == "PENDING" for r in ress),
        "survey_response_rate_pct": pct(len(scores), len(survs)),
        "mean_csat": round(mean(scores), 2) if scores else None,
        "messages_per_complaint": round(len(msgs) / n, 2),
        "status_events_per_complaint": round(len(events) / n, 2),
        "by_priority": sla_table,
        "complaints_by_category": {names[k]: v for k, v in sorted(Counter(c["category_id"] for c in complaints).items())},
    }
    report = {"classification": classification, "kpis": kpis}
    with open(os.path.join(args.out, "evaluation_report.json"), "w", newline="\n") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")

    print(f"Category accuracy : {classification['category_accuracy_pct']}%")
    print(f"Priority accuracy : {classification['priority_accuracy_pct']}%")
    print(f"Safety recall     : {classification['safety_recall_pct']}%")
    print(f"Priority mix %    : {kpis['priority_mix_pct']}")
    print(f"Repeat / vulnerable / reopen %: {kpis['repeat_rate_pct']} / {kpis['vulnerable_rate_pct']} / {kpis['reopen_rate_pct']}")
    print(f"Breach rate % overall: {kpis['overall_breach_rate_pct']}   by priority: "
          + ", ".join(f"{p}={v['breach_rate_pct']}" for p, v in sla_table.items()))
    print(f"Escalation rate % by priority: " + ", ".join(f"{p}={v['escalation_rate_pct']}" for p, v in sla_table.items()))
    print(f"Mean hours to first resolution: {kpis['mean_hours_to_first_resolution']}   mean CSAT: {kpis['mean_csat']}")
    print(f"Status mix: {kpis['status_mix']}")


if __name__ == "__main__":
    main()
