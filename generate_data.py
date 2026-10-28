#!/usr/bin/env python3
"""Synthetic complaint-management data generator (standard library only).

Usage:
    python generate_data.py                      # full dataset, seed 20261022
    python generate_data.py --customers 500 --orders 800 --complaints 200 --messages 600 --out starter

Order of work (parents first, then children):
    customers/products -> orders + order_items -> complaints (draw, classify, link repeats)
    -> priority -> status events -> assignments -> SLA clock -> resolution -> survey -> messages
    -> inject labelled anomalies -> write CSV / SQL / ground truth / manifest.
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
from datetime import date, datetime, time, timedelta

import rules as R
import schema_spec

DEFAULT_SEED = 20261022
START = date(2026, 1, 1)
ORDER_END = date(2026, 10, 5)

# ---------------------------------------------------------------- reference data
FIRST = ["Aarav", "Diya", "Rohan", "Sneha", "Karthik", "Priya", "Arjun", "Ananya", "Vikram", "Meera",
         "Rahul", "Kavya", "Suresh", "Lakshmi", "Imran", "Fatima", "John", "Maria", "Daniel", "Sara",
         "Amit", "Pooja", "Nikhil", "Ishita", "Varun", "Neha", "Manish", "Divya", "Harsh", "Tanvi"]
LAST = ["Sharma", "Reddy", "Patel", "Nair", "Iyer", "Khan", "Singh", "Gupta", "Rao", "Das",
        "Menon", "Joshi", "Verma", "Mehta", "Naidu", "Kumar", "Shah", "Bose", "Pillai", "Chopra",
        "Fernandes", "Thomas", "Mishra", "Kapoor", "Yadav", "Jain", "Agarwal", "Desai", "Sinha", "Malik"]
CITIES = ["Hyderabad", "Bengaluru", "Mumbai", "Delhi", "Chennai", "Pune", "Kolkata", "Ahmedabad", "Jaipur", "Kochi"]
CHANNELS = ["Email", "Phone", "Web Form", "Mobile App", "Social Media", "Chat"]
CHANNEL_WEIGHTS = [25, 20, 20, 15, 8, 12]

# (name, product category, price INR, hazard-prone)
PRODUCTS = [
    ("Wireless Earbuds", "Electronics", 2499, 0), ("Phone Charger 20W", "Electronics", 899, 1),
    ("Power Bank 10000mAh", "Electronics", 1799, 1), ("Bluetooth Speaker", "Electronics", 2999, 0),
    ("Smart Watch", "Electronics", 4999, 0), ("Headphones", "Electronics", 7999, 0),
    ("Electric Kettle", "Appliances", 1499, 1), ("Room Heater", "Appliances", 2999, 1),
    ("Induction Cooktop", "Appliances", 3499, 1), ("Mixer Grinder", "Appliances", 3999, 1),
    ("Air Fryer", "Appliances", 6999, 1), ("Hair Dryer", "Personal Care", 1299, 1),
    ("Electric Shaver", "Personal Care", 1799, 0), ("Laptop Sleeve", "Accessories", 799, 0),
    ("Backpack", "Accessories", 1599, 0), ("Running Shoes", "Footwear", 3299, 0),
    ("Yoga Mat", "Fitness", 999, 0), ("Water Bottle", "Home", 499, 0),
    ("Desk Lamp", "Home", 1199, 0), ("Office Chair", "Furniture", 8999, 0),
    ("Gaming Mouse", "Electronics", 1499, 0), ("Mechanical Keyboard", "Electronics", 2499, 0),
    ("Cotton Bedsheet", "Home", 1299, 0), ("Cookware Set", "Home", 2799, 0),
    ("4K Monitor", "Electronics", 18999, 0), ("Laptop", "Electronics", 54999, 0),
]

TEAMS = ["Logistics", "Product Quality", "Billing & Refunds", "Customer Care", "Safety & Compliance", "Escalations"]

# (id, name, default severity, owning team, weight in %)
CATEGORIES = [
    ("CAT-01", "Late Delivery", "Low", "Logistics", 20),
    ("CAT-02", "Missing Order", "High", "Logistics", 8),
    ("CAT-03", "Damaged Item", "Medium", "Logistics", 12),
    ("CAT-04", "Wrong Item", "Medium", "Logistics", 10),
    ("CAT-05", "Product Defect", "Medium", "Product Quality", 18),
    ("CAT-06", "Product Safety", "Critical", "Safety & Compliance", 3),
    ("CAT-07", "Refund Pending", "High", "Billing & Refunds", 10),
    ("CAT-08", "Billing Error", "Medium", "Billing & Refunds", 8),
    ("CAT-09", "Poor Service", "Low", "Customer Care", 8),
    ("CAT-10", "Account Issue", "Low", "Customer Care", 3),
]
CAT = {c[0]: c for c in CATEGORIES}
SAFETY_CAT = "CAT-06"
DEFAULT_CAT = "CAT-09"

PRIORITY_RULES = [
    dict(rule_id="PR-001", factor="is_safety_issue", operator="==", threshold=1, points=0, effect="FORCE_P1"),
    dict(rule_id="PR-002", factor="sentiment_score", operator="<=", threshold=-0.25, points=1, effect="ADD_POINTS"),
    dict(rule_id="PR-003", factor="sentiment_score", operator="<=", threshold=-0.5, points=1, effect="ADD_POINTS"),
    dict(rule_id="PR-004", factor="order_value", operator=">=", threshold=5000, points=1, effect="ADD_POINTS"),
    dict(rule_id="PR-005", factor="order_value", operator=">=", threshold=20000, points=1, effect="ADD_POINTS"),
    dict(rule_id="PR-006", factor="is_repeat", operator="==", threshold=1, points=2, effect="ADD_POINTS"),
    dict(rule_id="PR-007", factor="vulnerable_flag", operator="==", threshold=1, points=2, effect="ADD_POINTS"),
    dict(rule_id="PR-008", factor="severity_rank", operator=">=", threshold=3, points=1, effect="ADD_POINTS"),
]
for _r in PRIORITY_RULES:
    _r["effective_from"] = "2026-01-01"
    _r["effective_to"] = None

PRIORITY_LEVELS = [
    dict(priority_level="P1", min_points=6, sla_hours=24, queue="P1-URGENT", escalation_pct=R.ESCALATION_PCT),
    dict(priority_level="P2", min_points=4, sla_hours=72, queue="P2-HIGH", escalation_pct=R.ESCALATION_PCT),
    dict(priority_level="P3", min_points=2, sla_hours=120, queue="P3-STANDARD", escalation_pct=R.ESCALATION_PCT),
    dict(priority_level="P4", min_points=0, sla_hours=240, queue="P4-LOW", escalation_pct=R.ESCALATION_PCT),
]
LEVEL = {l["priority_level"]: l for l in PRIORITY_LEVELS}

# ---------------------------------------------------------------- text templates
TEMPLATES = {
    "CAT-01": ["My order {order} is very late. The {product} was supposed to arrive last week.",
               "The delivery of my {product} is delayed again.",
               "Order {order} is running late and nobody told me why."],
    "CAT-02": ["My order {order} never arrived and the tracking shows it as lost in transit.",
               "The {product} from order {order} is missing. I never received the parcel.",
               "My package for {order} was not delivered at all."],
    "CAT-03": ["The {product} arrived damaged and the box was crushed.",
               "My {product} is cracked right out of the box.",
               "I opened order {order} and the {product} was broken."],
    "CAT-04": ["I received the wrong item in order {order}. I ordered a {product}.",
               "This is not what I ordered. I wanted the {product}.",
               "They sent a different product than the {product} I ordered."],
    "CAT-05": ["The {product} stopped working after two days.",
               "My {product} is defective and does not switch on.",
               "The {product} is faulty and keeps going off."],
    "CAT-06": ["The {product} started to smoke and I had to unplug it.",
               "The {product} began to overheat and I got a small burn.",
               "I saw sparks from the {product} and got an electric shock."],
    "CAT-07": ["I returned the {product} but my refund has not come yet.",
               "Still waiting for my money back for order {order}.",
               "The refund for order {order} has been pending for weeks."],
    "CAT-08": ["I was charged twice for order {order}.",
               "I was overcharged for the {product}. The invoice looks wrong.",
               "There is a double charge on my card for {order}."],
    "CAT-09": ["The support agent was rude and unhelpful.",
               "I have had no response from your team for days.",
               "Nobody from support has called me back."],
    "CAT-10": ["I cannot sign in to my account and the password reset email never comes.",
               "My account is locked after a login attempt.",
               "I cannot log in, my password is not accepted."],
}
VAGUE = ["I am not happy with my {product}. Please look into this.",
         "Something went off with order {order}.",
         "I want to raise a complaint about order {order}."]

KEYWORDS = {  # order matters: safety first, ties go to the earlier entry
    "CAT-06": ["smoke", "burn", "overheat", "overheating", "sparks", "shock", "fire", "injured", "injury"],
    "CAT-02": ["missing", "never arrived", "never received", "lost in transit", "not delivered"],
    "CAT-01": ["late", "delayed", "delay"],
    "CAT-03": ["damaged", "cracked", "broken", "dented", "crushed"],
    "CAT-04": ["wrong item", "not what i ordered", "different product", "incorrect item"],
    "CAT-05": ["stopped working", "defective", "faulty", "malfunction", "not working"],
    "CAT-07": ["refund", "money back"],
    "CAT-08": ["charged twice", "overcharged", "double charge", "wrong amount", "invoice"],
    "CAT-09": ["rude", "unhelpful", "no response", "support", "agent"],
    "CAT-10": ["password", "login", "log in", "sign in", "account"],
}
NEG_PHRASES = ["This is unacceptable.", "I am furious.", "This is the worst experience.", "I am very disappointed.",
               "I am so frustrated.", "This is ridiculous.", "This is terrible.", "I am really upset."]
NEG_WORDS = {"unacceptable", "furious", "terrible", "worst", "angry", "awful", "disappointed", "upset", "frustrated", "ridiculous"}
POS_WORDS = {"thank", "thanks", "appreciate", "kindly", "grateful"}


def classify(text):
    """Keyword classifier: category with the most keyword hits wins, default Poor Service."""
    low = text.lower()
    best, best_hits = DEFAULT_CAT, 0
    for cat_id, words in KEYWORDS.items():
        hits = sum(1 for w in words if re.search(r"\b" + re.escape(w) + r"\b", low))
        if hits > best_hits:
            best, best_hits = cat_id, hits
    return best


def sentiment(text):
    words = re.findall(r"[a-z]+", text.lower())
    score = 0.25 * (sum(w in POS_WORDS for w in words) - sum(w in NEG_WORDS for w in words))
    return round(max(-1.0, min(1.0, score)), 2)


def build_text(rng, cat_id, tone, product_name, order_id):
    if cat_id != SAFETY_CAT and rng.random() < 0.08:      # vague text -> classifier will often miss
        core = rng.choice(VAGUE)
    else:
        core = rng.choice(TEMPLATES[cat_id])
    core = core.format(product=product_name, order=order_id)
    if tone == "angry":
        return " ".join(rng.sample(NEG_PHRASES, rng.choice([2, 3]))) + " " + core
    if tone == "polite":
        return "Hello, " + core + " Thank you, I appreciate your help."
    return "Hello, " + core


# ---------------------------------------------------------------- master data
def make_customers(rng, n):
    span = (date(2026, 8, 31) - date(2023, 1, 1)).days
    rows = []
    for i in range(1, n + 1):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        rows.append({
            "customer_id": f"CUS-{i:06d}", "full_name": f"{first} {last}",
            "email": f"{first.lower()}.{last.lower()}{i}@example.test",
            "city": rng.choice(CITIES), "segment": rng.choices(["Standard", "Premium", "VIP"], [70, 25, 5])[0],
            "vulnerable_flag": int(rng.random() < 0.04),
            "signup_date": (date(2023, 1, 1) + timedelta(days=rng.randint(0, span))).isoformat()})
    return rows


def make_products():
    return [{"product_id": f"PRD-{i:04d}", "product_name": n, "product_category": c,
             "unit_price": float(p), "is_hazard_prone": h} for i, (n, c, p, h) in enumerate(PRODUCTS, 1)]


def make_orders(rng, customers, products, n):
    drafts = []
    for k in range(n):
        cust = rng.choice(customers)
        lo = max(date.fromisoformat(cust["signup_date"]), START)
        order_date = lo + timedelta(days=rng.randint(0, (ORDER_END - lo).days))
        promised = order_date + timedelta(days=5)
        if rng.random() < 0.03:
            delivered, status = None, "LOST"
        else:
            lag = rng.choices(range(2, 11), weights=[10, 20, 25, 20, 8, 6, 5, 3, 3])[0]
            delivered = order_date + timedelta(days=lag)
            status = "LATE" if delivered > promised else "DELIVERED"
        picked = rng.sample(products, rng.choices([1, 2, 3], [70, 22, 8])[0])
        lines = [(p, rng.choices([1, 2, 3], [75, 20, 5])[0]) for p in picked]
        drafts.append(dict(k=k, cust=cust["customer_id"], order_date=order_date, promised=promised,
                           delivered=delivered, status=status, lines=lines,
                           channel=rng.choices(["Web", "Mobile App", "Marketplace"], [45, 35, 20])[0]))
    drafts.sort(key=lambda d: (d["order_date"], d["k"]))
    orders, items = [], []
    for i, d in enumerate(drafts, 1):
        oid = f"ORD-2026-{i:06d}"
        total = 0.0
        for p, q in d["lines"]:
            line = round(q * p["unit_price"], 2)
            total += line
            items.append({"order_id": oid, "product_id": p["product_id"], "quantity": q,
                          "unit_price": p["unit_price"], "line_total": line})
        orders.append({"order_id": oid, "customer_id": d["cust"], "order_date": d["order_date"].isoformat(),
                       "promised_date": d["promised"].isoformat(),
                       "delivered_date": d["delivered"].isoformat() if d["delivered"] else None,
                       "delivery_status": d["status"], "order_channel": d["channel"],
                       "order_total": round(total, 2)})
    return orders, items


# ---------------------------------------------------------------- complaints
def draw_complaints(rng, n, orders, items_by_order, prod_by_id):
    """Pick (order, product, category, created_at, text) for n complaints. IDs are given later."""
    hazard = [o for o in orders if any(prod_by_id[i["product_id"]]["is_hazard_prone"] for i in items_by_order[o["order_id"]])]
    pools = {"CAT-01": [o for o in orders if o["delivery_status"] == "LATE"],
             "CAT-02": [o for o in orders if o["delivery_status"] == "LOST"],
             "CAT-06": hazard}
    weights = [c[4] for c in CATEGORIES]
    n_follow = round(n * 0.10)          # deliberate repeat complaints
    n_base = n - n_follow
    used_orders, drafts = set(), []

    def make_draft(cust, order_id, product_id, cat_id, created):
        tone = rng.choices(["angry", "neutral", "polite"], [30, 45, 25])[0]
        text = build_text(rng, cat_id, tone, prod_by_id[product_id]["product_name"], order_id)
        drafts.append(dict(k=len(drafts), customer_id=cust, order_id=order_id, product_id=product_id,
                           true_cat=cat_id, created=created, text=text,
                           channel=rng.choices(CHANNELS, CHANNEL_WEIGHTS)[0]))

    def base_draft():
        cat_id = rng.choices(CATEGORIES, weights)[0][0]
        pool = pools.get(cat_id) or orders
        if not pool:
            pool = orders
        for attempt in range(40):
            order = rng.choice(pool)
            if attempt < 20 and order["order_id"] in used_orders:
                continue
            base = date.fromisoformat(order["delivered_date"] or order["promised_date"])
            days = rng.uniform(1, 10) if order["delivery_status"] == "LOST" else rng.uniform(0.1, 15)
            created = datetime.combine(base, time(0, 0)) + timedelta(minutes=int(days * 1440))
            if created <= R.AS_OF:
                break
        else:
            return
        lines = items_by_order[order["order_id"]]
        if cat_id == SAFETY_CAT:
            lines = [i for i in lines if prod_by_id[i["product_id"]]["is_hazard_prone"]] or lines
        used_orders.add(order["order_id"])
        make_draft(order["customer_id"], order["order_id"], rng.choice(lines)["product_id"], cat_id, created)

    while len(drafts) < n_base:
        base_draft()
    tries = 0
    while len(drafts) < n:
        tries += 1
        parent = rng.choice(drafts)
        created = parent["created"] + timedelta(minutes=rng.randint(2 * 1440, 25 * 1440))
        if created <= R.AS_OF:
            make_draft(parent["customer_id"], parent["order_id"], parent["product_id"], parent["true_cat"], created)
        elif tries > 200:
            base_draft()
    return drafts


def make_timeline(rng, sla_min, esc_min):
    """Minute offsets from created_at for one complaint life-cycle (before the data cut-off).

    W = working minutes needed to resolve (pauses are NOT counted in W).
    Most complaints finish inside the SLA; some breach; a few are exact boundary cases.
    """
    r = rng.random()
    if r < 0.02:
        W, scenario = sla_min, "BOUNDARY_ON_DEADLINE"
    elif r < 0.04:
        W, scenario = esc_min, "BOUNDARY_AT_ESCALATION_THRESHOLD"
    else:
        W, scenario = max(180, int(sla_min * rng.betavariate(2, 3) * 1.45)), "NORMAL"
    a, b = rng.randint(5, 90), rng.randint(10, 60)
    steps = [("NEW", 0, "SYSTEM"), ("ASSIGNED", a, "SYSTEM"), ("IN_PROGRESS", a + b, "AGENT")]
    pause = 0
    if W > esc_min:                                   # escalation rule: working time > 75% of SLA
        steps += [("ESCALATED", esc_min, "SYSTEM"), ("RESOLVED", W, "AGENT")]
    else:
        if W >= 240 and rng.random() < 0.25:         # customer-wait pause (SLA clock stops)
            start = max(int(W * rng.uniform(0.3, 0.7)), a + b + 15)
            if start < W - 30:
                pause = rng.randint(120, 2880)
                steps += [("WAITING_CUSTOMER", start, "AGENT"), ("IN_PROGRESS", start + pause, "CUSTOMER")]
        steps.append(("RESOLVED", W + pause, "AGENT"))
    closed = steps[-1][1] + rng.randint(1440, 4320)
    steps.append(("CLOSED", closed, "SYSTEM"))
    if rng.random() < 0.08:                           # reopened case
        reopen = closed + rng.randint(1440, 10080)
        back = reopen + rng.randint(30, 360)
        again = back + rng.randint(480, 4320)
        steps += [("REOPENED", reopen, "CUSTOMER"), ("IN_PROGRESS", back, "AGENT"),
                  ("RESOLVED", again, "AGENT"), ("CLOSED", again + rng.randint(1440, 4320), "SYSTEM")]
    return steps, scenario


EVENT_NOTES = {"NEW": "Complaint logged", "ASSIGNED": "Assigned to team queue", "IN_PROGRESS": "Work started",
               "WAITING_CUSTOMER": "Waiting for customer information; SLA clock paused",
               "ESCALATED": "SLA escalation threshold reached", "RESOLVED": "Resolution applied",
               "CLOSED": "Closed after confirmation window", "REOPENED": "Customer reopened the complaint"}
MSG_RANK = {"CUSTOMER_COMPLAINT": 0, "AGENT_ACK": 1, "AGENT_INFO_REQUEST": 2, "CUSTOMER_REPLY": 3,
            "SYSTEM_ESCALATION_NOTICE": 4, "AGENT_UPDATE": 5, "AGENT_RESOLUTION_NOTICE": 6,
            "SYSTEM_CLOSURE_NOTICE": 7, "CUSTOMER_REOPEN_REQUEST": 8}
RES_TYPES = {"CAT-01": [("CREDIT", 70), ("APOLOGY_EXPLANATION", 30)], "CAT-02": [("REFUND", 60), ("REPLACEMENT", 40)],
             "CAT-03": [("REPLACEMENT", 50), ("REFUND", 50)], "CAT-04": [("REPLACEMENT", 70), ("REFUND", 30)],
             "CAT-05": [("REPAIR", 35), ("REPLACEMENT", 40), ("REFUND", 25)],
             "CAT-06": [("REFUND", 70), ("REPLACEMENT", 30)], "CAT-07": [("REFUND", 100)],
             "CAT-08": [("REFUND", 100)], "CAT-09": [("APOLOGY_EXPLANATION", 70), ("CREDIT", 30)],
             "CAT-10": [("APOLOGY_EXPLANATION", 100)]}


def paused_minutes(events):
    """Minutes spent in WAITING_CUSTOMER, computed from the events only. events = [(status, datetime)]."""
    total = 0
    for i, (status, t) in enumerate(events):
        if status == "WAITING_CUSTOMER":
            end = events[i + 1][1] if i + 1 < len(events) else R.AS_OF
            total += int((end - t).total_seconds() // 60)
    return total


def build_case(rng, c, agents_by_team, level):
    """Create every child record of one complaint. Returns dict of lists."""
    cid = c["complaint_id"]
    created = c["_created"]
    sla_min = level["sla_hours"] * 60
    esc_min = int(sla_min * level["escalation_pct"])
    steps, scenario = make_timeline(rng, sla_min, esc_min)
    events = [(s, created + timedelta(minutes=m), actor) for s, m, actor in steps]
    events = [e for e in events if e[1] <= R.AS_OF]               # nothing after the cut-off
    ev_rows, prev = [], None
    for n, (status, t, actor) in enumerate(events, 1):
        note = EVENT_NOTES[status]
        if status == "IN_PROGRESS" and prev == "WAITING_CUSTOMER":
            note = "Customer replied; SLA clock resumed"
        ev_rows.append({"event_id": f"EVT-{cid}-{n:03d}", "complaint_id": cid, "from_status": prev,
                        "to_status": status, "event_time": R.ts(t), "actor_type": actor, "note": note})
        prev = status
    c["current_status"] = events[-1][0]
    ev_pairs = [(s, t) for s, t, _ in events]

    # ---- assignments (ownership history)
    team = "Safety & Compliance" if c["is_safety_issue"] else CAT[c["category_id"]][3]
    asg = []

    def add_asg(team_name, queue, reason, when):
        if asg:
            asg[-1]["ended_at"] = R.ts(when)
            asg[-1]["is_current"] = 0
        asg.append({"assignment_id": f"ASG-{cid}-{len(asg) + 1:02d}", "complaint_id": cid,
                    "agent_id": rng.choice(agents_by_team[team_name]), "team": team_name, "queue": queue,
                    "reason": reason, "assigned_at": R.ts(when), "ended_at": None, "is_current": 1})
    for status, t, _ in events:
        if status == "ASSIGNED":
            add_asg(team, level["queue"], "INITIAL", t)
        elif status == "ESCALATED":
            add_asg("Escalations", "ESCALATION", "ESCALATION", t)
        elif status == "REOPENED":
            add_asg(team, level["queue"], "REOPEN", t)

    # ---- SLA clock (derived from events)
    pause_min = paused_minutes(ev_pairs)
    paused_hours = round(pause_min / 60, 2)
    deadline = created + timedelta(minutes=sla_min + pause_min)
    resolved_times = [t for s, t in ev_pairs if s == "RESOLVED"]
    stopped = resolved_times[0] if resolved_times else None
    esc_times = [t for s, t in ev_pairs if s == "ESCALATED"]
    breached = int((stopped or R.AS_OF) > deadline)
    sla = {"sla_id": f"SLA-{cid}", "complaint_id": cid, "priority_level": c["priority_level"],
           "sla_hours": level["sla_hours"], "started_at": R.ts(created), "paused_hours": paused_hours,
           "pause_count": sum(1 for s, _ in ev_pairs if s == "WAITING_CUSTOMER"),
           "deadline_at": R.ts(deadline), "stopped_at": R.ts(stopped) if stopped else None,
           "escalated_at": R.ts(esc_times[0]) if esc_times else None, "is_breached": breached}

    # ---- resolution
    resolution = None
    reopen_count = sum(1 for s, _ in ev_pairs if s == "REOPENED")
    if resolved_times:
        options = RES_TYPES[c["category_id"]]
        rtype = rng.choices([o[0] for o in options], [o[1] for o in options])[0]
        value = c["order_value"]
        amount, refund_status = 0.0, "NOT_APPLICABLE"
        if rtype == "REFUND":
            portion = rng.choice([0.05, 0.1, 0.15]) if c["category_id"] == "CAT-08" else rng.choice([1.0, 1.0, 0.5])
            amount = round(value * portion, 2)
            paid_at = resolved_times[-1] + timedelta(days=rng.randint(1, 7))
            refund_status = "PAID" if paid_at <= R.AS_OF else "PENDING"
        elif rtype == "CREDIT":
            amount, refund_status = round(value * 0.1, 2), "PAID"
        owner = [a for a in asg if R.parse_ts(a["assigned_at"]) <= resolved_times[-1]][-1]
        resolution = {"resolution_id": f"RES-{cid}", "complaint_id": cid, "resolution_type": rtype,
                      "refund_amount": amount, "refund_status": refund_status,
                      "first_resolved_at": R.ts(resolved_times[0]), "resolved_at": R.ts(resolved_times[-1]),
                      "reopen_count": reopen_count, "resolved_by_agent_id": owner["agent_id"]}

    # ---- survey (only after the final CLOSED event)
    survey = None
    if events[-1][0] == "CLOSED" and rng.random() < 0.95:
        sent = events[-1][1] + timedelta(minutes=rng.randint(5, 120))
        if sent <= R.AS_OF:
            responded, score = None, None
            if rng.random() < 0.55:
                responded = sent + timedelta(minutes=rng.randint(30, 4320))
                if responded <= R.AS_OF:
                    raw = 4.2 - 1.0 * breached - 0.6 * bool(esc_times) - 0.8 * (reopen_count > 0) + rng.gauss(0, 0.8)
                    score = int(max(1, min(5, round(raw))))
                else:
                    responded = None
            survey = {"survey_id": f"SVY-{cid}", "complaint_id": cid, "sent_at": R.ts(sent),
                      "responded_at": R.ts(responded) if responded else None, "csat_score": score}

    # ---- candidate messages (some required, some optional so the total can match the target)
    msgs = []

    def add_msg(kind, sender, when, text, required):
        msgs.append({"complaint_id": cid, "sender_type": sender, "message_kind": kind, "channel": c["channel"],
                     "sent_at": when, "message_text": text, "_required": required})
    add_msg("CUSTOMER_COMPLAINT", "CUSTOMER", created, c["_text"], True)
    prev = None
    for status, t, _ in events:
        if status == "ASSIGNED":
            add_msg("AGENT_ACK", "AGENT", t, f"Thank you for contacting us. Complaint {cid} is now with our {team} team.", False)
        elif status == "WAITING_CUSTOMER":
            add_msg("AGENT_INFO_REQUEST", "AGENT", t, "Could you please share more details or photos so we can investigate?", True)
        elif status == "IN_PROGRESS" and prev == "WAITING_CUSTOMER":
            add_msg("CUSTOMER_REPLY", "CUSTOMER", t, "Here are the details you asked for.", True)
        elif status == "ESCALATED":
            add_msg("SYSTEM_ESCALATION_NOTICE", "SYSTEM", t, "Your complaint was escalated to a senior team.", False)
        elif status == "RESOLVED":
            add_msg("AGENT_RESOLUTION_NOTICE", "AGENT", t,
                    f"Your complaint has been resolved ({resolution['resolution_type'].lower().replace('_', ' ')}).", False)
        elif status == "CLOSED":
            add_msg("SYSTEM_CLOSURE_NOTICE", "SYSTEM", t, "Your complaint has been closed.", False)
        elif status == "REOPENED":
            add_msg("CUSTOMER_REOPEN_REQUEST", "CUSTOMER", t, "The problem has come back. Please reopen my complaint.", True)
        prev = status

    # window in which an extra AGENT_UPDATE may be sent
    in_prog = [t for s, t in ev_pairs if s == "IN_PROGRESS"]
    window = (in_prog[0], ev_pairs[-1][1]) if in_prog else None
    return dict(events=ev_rows, assignments=asg, sla=sla, resolution=resolution, survey=survey,
                messages=msgs, scenario=scenario if resolved_times else "NORMAL",
                escalated=bool(esc_times), window=window)


def pick_messages(rng, cases, target):
    """Return exactly `target` messages: all required ones + a random subset of optional ones.
    If there are not enough optional messages, add AGENT_UPDATE messages."""
    required = [m for k in cases for m in cases[k]["messages"] if m["_required"]]
    optional = [m for k in cases for m in cases[k]["messages"] if not m["_required"]]
    if target < len(required):
        sys.exit(f"--messages {target} is too low: at least {len(required)} messages are needed "
                 f"(one per complaint plus pause/reopen messages).")
    want = target - len(required)
    if want <= len(optional):
        chosen = rng.sample(optional, want)
    else:
        chosen = list(optional)
        spots = [(k, v["window"]) for k, v in cases.items() if v["window"] and
                 (v["window"][1] - v["window"][0]).total_seconds() >= 20 * 60]
        if not spots:
            sys.exit("Cannot add enough extra messages; lower --messages.")
        for _ in range(want - len(optional)):
            k, (lo, hi) = rng.choice(spots)
            span = int((hi - lo).total_seconds() // 60)
            chosen.append({"complaint_id": k, "sender_type": "AGENT", "message_kind": "AGENT_UPDATE",
                           "channel": None, "sent_at": lo + timedelta(minutes=rng.randint(5, span - 5)),
                           "message_text": "We are still working on your complaint and will update you soon.",
                           "_required": False})
    final = required + chosen
    grouped = {}
    for m in final:
        grouped.setdefault(m["complaint_id"], []).append(m)
    rows = []
    for cid in sorted(grouped):
        channel = cases[cid]["messages"][0]["channel"]
        msgs = sorted(grouped[cid], key=lambda m: (m["sent_at"], MSG_RANK[m["message_kind"]]))
        for n, m in enumerate(msgs, 1):
            rows.append({"message_id": f"MSG-{cid}-{n:03d}", "complaint_id": cid, "sender_type": m["sender_type"],
                         "message_kind": m["message_kind"], "channel": channel,
                         "sent_at": R.ts(m["sent_at"]), "message_text": m["message_text"]})
    return rows


# ---------------------------------------------------------------- main build
def build(args):
    rng = random.Random(args.seed)
    customers = make_customers(rng, args.customers)
    products = make_products()
    prod_by_id = {p["product_id"]: p for p in products}
    orders, items = make_orders(rng, customers, products, args.orders)
    cust_by_id = {c["customer_id"]: c for c in customers}
    order_by_id = {o["order_id"]: o for o in orders}
    items_by_order = {}
    for it in items:
        items_by_order.setdefault(it["order_id"], []).append(it)

    drafts = draw_complaints(rng, args.complaints, orders, items_by_order, prod_by_id)
    drafts.sort(key=lambda d: (d["created"], d["k"]))
    complaints = []
    for i, d in enumerate(drafts, 1):
        cat_id = classify(d["text"])
        c = {"complaint_id": f"CMP-2026-{i:06d}", "customer_id": d["customer_id"], "order_id": d["order_id"],
             "product_id": d["product_id"], "channel": d["channel"], "category_id": cat_id,
             "severity": CAT[cat_id][2], "sentiment_score": sentiment(d["text"]),
             "is_safety_issue": int(cat_id == SAFETY_CAT), "is_repeat": 0, "repeat_of_complaint_id": "",
             "vulnerable_flag": cust_by_id[d["customer_id"]]["vulnerable_flag"],
             "order_value": order_by_id[d["order_id"]]["order_total"], "priority_level": "",
             "created_at": R.ts(d["created"]), "current_status": "",
             "_created": d["created"], "_text": d["text"], "_true_cat": d["true_cat"]}
        complaints.append(c)

    # repeat rule: same customer + product + category within 30 days of an earlier complaint
    window = timedelta(days=R.REPEAT_WINDOW_DAYS)
    last, last_true = {}, {}
    for c in complaints:
        for store, cat_key, out in ((last, "category_id", "_link"), (last_true, "_true_cat", "_true_link")):
            key = (c["customer_id"], c["product_id"], c[cat_key])
            prev = store.get(key)
            c[out] = prev[1] if prev and c["_created"] - prev[0] <= window else ""
            store[key] = (c["_created"], c["complaint_id"])

    # choose complaints for the two anomalies that must happen BEFORE priority/SLA are derived
    used = set()

    def pick(eligible_ids, k):
        pool = [x for x in eligible_ids if x not in used]
        chosen = rng.sample(pool, min(k, len(pool)))
        used.update(chosen)
        return chosen
    linked = {c["_link"] for c in complaints if c["_link"]} | {c["complaint_id"] for c in complaints if c["_link"]}
    a4 = set(pick([c["complaint_id"] for c in complaints if c["_link"]], args.anomalies))
    a1 = set(pick([c["complaint_id"] for c in complaints if c["complaint_id"] not in linked], args.anomalies))

    # priority from rules (stored decision) and expected priority from TRUE attributes (ground truth)
    truth = {}
    for c in complaints:
        link = "" if c["complaint_id"] in a4 else c["_link"]
        c["repeat_of_complaint_id"] = link
        c["is_repeat"] = int(bool(link))
        c["priority_level"] = R.compute_priority(PRIORITY_RULES, PRIORITY_LEVELS, R.priority_facts(c))
        t = dict(c)
        t.update(is_safety_issue=int(c["_true_cat"] == SAFETY_CAT), severity=CAT[c["_true_cat"]][2],
                 is_repeat=int(bool(c["_true_link"])))
        exp_team = "Safety & Compliance" if t["is_safety_issue"] else CAT[c["_true_cat"]][3]
        exp_pr = R.compute_priority(PRIORITY_RULES, PRIORITY_LEVELS, R.priority_facts(t))
        truth[c["complaint_id"]] = {"complaint_id": c["complaint_id"], "true_category_id": c["_true_cat"],
                                    "expected_priority_level": exp_pr, "expected_team": exp_team,
                                    "expected_sla_hours": LEVEL[exp_pr]["sla_hours"], "expected_escalation": 0,
                                    "scenario": "NORMAL", "issue_type": "", "affected_entity": "",
                                    "affected_record_id": "", "issue_note": ""}

    agents = []
    for team in TEAMS:
        for _ in range(5):
            n = len(agents) + 1
            agents.append({"agent_id": f"AGT-{n:03d}", "agent_name": f"Agent {n:02d}", "team": team})
    agents_by_team = {t: [a["agent_id"] for a in agents if a["team"] == t] for t in TEAMS}

    cases = {}
    for c in complaints:
        case = build_case(rng, c, agents_by_team, LEVEL[c["priority_level"]])
        cases[c["complaint_id"]] = case
        truth[c["complaint_id"]]["expected_escalation"] = int(case["escalated"])
        truth[c["complaint_id"]]["scenario"] = case["scenario"]
    messages = pick_messages(rng, cases, args.messages)

    # ---- inject the remaining labelled anomalies (each complaint gets at most one)
    def mark(cid, issue, entity, record, note):
        truth[cid].update(issue_type=issue, affected_entity=entity, affected_record_id=record, issue_note=note)
    for cid in a4:
        mark(cid, "REPEAT_NOT_LINKED", "complaints", cid, "Repeat complaint left without repeat_of_complaint_id")
    by_id = {c["complaint_id"]: c for c in complaints}
    for cid in a1:
        by_id[cid]["customer_id"] = ""
        mark(cid, "COMPLAINT_WITHOUT_CUSTOMER", "complaints", cid, "customer_id is blank")

    for cid in pick([k for k, v in cases.items() if v["resolution"] and v["resolution"]["reopen_count"] == 0], args.anomalies):
        res = cases[cid]["resolution"]
        bad = R.ts(by_id[cid]["_created"] - timedelta(minutes=rng.randint(60, 2880)))
        res["first_resolved_at"] = res["resolved_at"] = bad
        mark(cid, "RESOLUTION_BEFORE_COMPLAINT", "resolutions", res["resolution_id"], "Resolution time is before complaint creation")

    for cid in pick(list(cases), args.anomalies):
        sla = cases[cid]["sla"]
        if sla["pause_count"] > 0:
            sla["paused_hours"], sla["pause_count"], note = 0.0, 0, "Real customer-wait pause was ignored"
        else:
            sla["paused_hours"], sla["pause_count"] = round(rng.uniform(6, 48), 1), 1
            note = "Pause applied although the complaint never waited for the customer"
        deadline = by_id[cid]["_created"] + timedelta(minutes=sla["sla_hours"] * 60 + sla["paused_hours"] * 60)
        sla["deadline_at"] = R.ts(deadline)
        stopped = R.parse_ts(sla["stopped_at"]) if sla["stopped_at"] else R.AS_OF
        sla["is_breached"] = int(stopped > deadline)
        mark(cid, "SLA_CLOCK_PAUSES_INCORRECTLY", "sla_clocks", sla["sla_id"], note)

    safety = [k for k, v in cases.items() if by_id[k]["is_safety_issue"] and v["assignments"]]
    for cid in pick(safety, args.anomalies):
        first = cases[cid]["assignments"][0]
        first.update(team="Customer Care", queue="P4-LOW", agent_id=rng.choice(agents_by_team["Customer Care"]))
        mark(cid, "CRITICAL_SAFETY_LOW_PRIORITY_QUEUE", "assignments", first["assignment_id"],
             "Safety complaint placed in Customer Care / P4-LOW queue")

    one_close = [k for k, v in cases.items() if v["survey"] and v["resolution"] and v["resolution"]["reopen_count"] == 0]
    for cid in pick(one_close, args.anomalies):
        sv, res = cases[cid]["survey"], cases[cid]["resolution"]
        closed = next(R.parse_ts(e["event_time"]) for e in cases[cid]["events"] if e["to_status"] == "CLOSED")
        resolved = R.parse_ts(res["resolved_at"])
        delay = (R.parse_ts(sv["responded_at"]) - R.parse_ts(sv["sent_at"])) if sv["responded_at"] else None
        new_sent = resolved + (closed - resolved) / 2
        sv["sent_at"] = R.ts(new_sent)
        if delay:
            sv["responded_at"] = R.ts(new_sent + delay)
        mark(cid, "SURVEY_BEFORE_CLOSURE", "surveys", sv["survey_id"], "Survey sent before the complaint was closed")

    tables = {
        "customers": customers, "products": products, "orders": orders, "order_items": items,
        "categories": [{"category_id": c[0], "category_name": c[1], "default_severity": c[2], "owning_team": c[3],
                        "is_active": 1, "effective_from": "2026-01-01", "effective_to": None} for c in CATEGORIES],
        "priority_rules": PRIORITY_RULES, "priority_levels": PRIORITY_LEVELS, "agents": agents,
        "complaints": complaints,
        "complaint_status_events": [e for k in cases for e in cases[k]["events"]],
        "complaint_messages": messages,
        "assignments": [a for k in cases for a in cases[k]["assignments"]],
        "sla_clocks": [cases[k]["sla"] for k in cases],
        "resolutions": [cases[k]["resolution"] for k in cases if cases[k]["resolution"]],
        "surveys": [cases[k]["survey"] for k in cases if cases[k]["survey"]],
    }
    return tables, [truth[c["complaint_id"]] for c in complaints]


# ---------------------------------------------------------------- output
def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(fields)
        for r in rows:
            w.writerow(["" if r[f] is None else r[f] for f in fields])


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def write_sql_seed(path, tables):
    db = sqlite3.connect(":memory:")
    db.executescript(schema_spec.schema_sql())
    for name, spec in schema_spec.TABLES.items():
        fields = spec["fields"]
        sql = f"INSERT INTO {name} ({', '.join(f[0] for f in fields)}) VALUES ({', '.join('?' * len(fields))})"
        data = []
        for r in tables[name]:
            # blank text in an OPTIONAL column becomes NULL; required columns keep '' (see README)
            data.append([None if (r[f[0]] is None or (r[f[0]] == "" and f[2] == "N")) else r[f[0]] for f in fields])
        db.executemany(sql, data)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for line in db.iterdump():
            fh.write(line + "\n")
    db.close()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--customers", type=int, default=5000)
    p.add_argument("--orders", type=int, default=8000)
    p.add_argument("--complaints", type=int, default=2000)
    p.add_argument("--messages", type=int, default=6000)
    p.add_argument("--anomalies", type=int, default=None, help="anomalies per type (default: complaints/200, min 2)")
    p.add_argument("--out", default="output")
    args = p.parse_args()
    if args.anomalies is None:
        args.anomalies = max(2, args.complaints // 200)

    tables, truth = build(args)
    for sub in ("data", "ground_truth", "sql", "docs"):
        os.makedirs(os.path.join(args.out, sub), exist_ok=True)
    files = []
    for name, spec in schema_spec.TABLES.items():
        path = os.path.join(args.out, "data", f"{name}.csv")
        write_csv(path, [f[0] for f in spec["fields"]], tables[name])
        files.append(path)
    gt_path = os.path.join(args.out, "ground_truth", "ground_truth.csv")
    write_csv(gt_path, schema_spec.GROUND_TRUTH_FIELDS, truth)
    files.append(gt_path)
    schema_path = os.path.join(args.out, "sql", "schema.sql")
    with open(schema_path, "w", newline="\n") as fh:
        fh.write(schema_spec.schema_sql())
    seed_path = os.path.join(args.out, "sql", "seed.sql")
    write_sql_seed(seed_path, tables)
    files += [schema_path, seed_path]
    with open(os.path.join(args.out, "docs", "data_dictionary.md"), "w", newline="\n") as fh:
        fh.write(schema_spec.data_dictionary_md())

    manifest = {
        "generator_command": "python generate_data.py " + " ".join(sys.argv[1:]),
        "seed": args.seed, "as_of": R.ts(R.AS_OF), "python_version": sys.version.split()[0],
        "parameters": {"customers": args.customers, "orders": args.orders, "complaints": args.complaints,
                       "messages": args.messages, "anomalies_per_type": args.anomalies},
        "row_counts": {n: len(tables[n]) for n in tables},
        "sha256": {os.path.relpath(f, args.out).replace(os.sep, "/"): sha256(f) for f in files},
        "sources": [{"source": "none", "note": "All data is synthetic and generated from code. No external or public dataset is used, so there is no licence or personal-data concern."}],
    }
    with open(os.path.join(args.out, "manifest.json"), "w", newline="\n") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")
    print(f"Done -> {args.out}/   (seed {args.seed})")
    for n, cnt in manifest["row_counts"].items():
        print(f"  {n:26s}{cnt:>7}")


if __name__ == "__main__":
    main()
