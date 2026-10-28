"""Business rules shared by the generator and the validator."""
from datetime import datetime

AS_OF = datetime(2026, 10, 22, 23, 59, 0)   # data cut-off ("today" inside the dataset)
ESCALATION_PCT = 0.75
REPEAT_WINDOW_DAYS = 30

SEVERITY_RANK = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}

# Allowed status changes. None = the very first event of a complaint.
TRANSITIONS = {
    None: {"NEW"},
    "NEW": {"ASSIGNED"},
    "ASSIGNED": {"IN_PROGRESS"},
    "IN_PROGRESS": {"WAITING_CUSTOMER", "ESCALATED", "RESOLVED"},
    "WAITING_CUSTOMER": {"IN_PROGRESS"},
    "ESCALATED": {"RESOLVED"},
    "RESOLVED": {"CLOSED"},
    "CLOSED": {"REOPENED"},
    "REOPENED": {"IN_PROGRESS"},
}


def ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def parse_ts(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def rule_matches(rule, facts):
    value = float(facts[rule["factor"]])
    threshold = float(rule["threshold"])
    if rule["operator"] == ">=":
        return value >= threshold
    if rule["operator"] == "<=":
        return value <= threshold
    return value == threshold


def compute_priority(rules, levels, facts):
    """Return 'P1'..'P4'.

    1. A matching FORCE_P1 rule (product safety) wins immediately.
    2. Otherwise add up the points of all matching ADD_POINTS rules and pick the
       highest level whose min_points is reached.
    """
    points = 0
    for rule in rules:
        if rule_matches(rule, facts):
            if rule["effect"] == "FORCE_P1":
                return "P1"
            points += int(rule["points"])
    for level in sorted(levels, key=lambda l: -int(l["min_points"])):
        if points >= int(level["min_points"]):
            return level["priority_level"]
    return levels[-1]["priority_level"]


def priority_facts(c):
    """Pull the rule inputs out of a complaint row (works for CSV strings too)."""
    return {
        "is_safety_issue": int(c["is_safety_issue"]),
        "sentiment_score": float(c["sentiment_score"]),
        "order_value": float(c["order_value"]),
        "is_repeat": int(c["is_repeat"]),
        "vulnerable_flag": int(c["vulnerable_flag"]),
        "severity_rank": SEVERITY_RANK[c["severity"]],
    }
