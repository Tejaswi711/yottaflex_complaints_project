"""Single source of truth for every table.

The generator uses it for CSV headers, and it also writes schema.sql and
data_dictionary.md, so the three can never drift apart.

Field tuple = (name, type, required Y/N, allowed values / validation rule)
Types: TEXT, INTEGER, REAL, DATE, DATETIME, BOOL (0/1)
"""

SQL_TYPES = {"TEXT": "TEXT", "INTEGER": "INTEGER", "REAL": "REAL",
             "DATE": "TEXT", "DATETIME": "TEXT", "BOOL": "INTEGER"}

TABLES = {
    "customers": dict(
        desc="Master data. One row per synthetic customer.",
        rel="Customer 1:N Order, Customer 1:N Complaint.",
        pk=["customer_id"], unique=["email"], fks=[],
        fields=[
            ("customer_id", "TEXT", "Y", "CUS-nnnnnn, unique, immutable"),
            ("full_name", "TEXT", "Y", "Synthetic name"),
            ("email", "TEXT", "Y", "Unique, always @example.test (not a real address)"),
            ("city", "TEXT", "Y", "One of a fixed city list"),
            ("segment", "TEXT", "Y", "Standard | Premium | VIP"),
            ("vulnerable_flag", "BOOL", "Y", "0/1, synthetic only; 1 = needs extra care"),
            ("signup_date", "DATE", "Y", "YYYY-MM-DD, on or before 2026-08-31"),
        ]),
    "products": dict(
        desc="Master data. One row per product.",
        rel="Product N:M Order (via order_items), Product 1:N Complaint.",
        pk=["product_id"], unique=[], fks=[],
        fields=[
            ("product_id", "TEXT", "Y", "PRD-nnnn, unique"),
            ("product_name", "TEXT", "Y", "Free text"),
            ("product_category", "TEXT", "Y", "Free text"),
            ("unit_price", "REAL", "Y", "INR, > 0"),
            ("is_hazard_prone", "BOOL", "Y", "0/1; 1 = electrical/heat product where safety complaints are plausible"),
        ]),
    "orders": dict(
        desc="Master data. One row per order. order_total is derived from order_items.",
        rel="Customer 1:N Order; Order N:M Product via order_items; Order 1:N Complaint.",
        pk=["order_id"], unique=[], fks=[("customer_id", "customers", "customer_id")],
        fields=[
            ("order_id", "TEXT", "Y", "ORD-2026-nnnnnn, unique"),
            ("customer_id", "TEXT", "Y", "FK customers"),
            ("order_date", "DATE", "Y", "On/after customer signup_date"),
            ("promised_date", "DATE", "Y", "order_date + 5 days"),
            ("delivered_date", "DATE", "N", "Blank when delivery_status = LOST; otherwise >= order_date"),
            ("delivery_status", "TEXT", "Y", "DELIVERED | LATE | LOST. LATE if delivered_date > promised_date"),
            ("order_channel", "TEXT", "Y", "Web | Mobile App | Marketplace"),
            ("order_total", "REAL", "Y", "INR. Derived: sum of order_items.line_total"),
        ]),
    "order_items": dict(
        desc="Bridge table that resolves the many-to-many between Order and Product.",
        rel="Order 1:N order_items N:1 Product.",
        pk=["order_id", "product_id"], unique=[],
        fks=[("order_id", "orders", "order_id"), ("product_id", "products", "product_id")],
        fields=[
            ("order_id", "TEXT", "Y", "FK orders"),
            ("product_id", "TEXT", "Y", "FK products"),
            ("quantity", "INTEGER", "Y", "1 to 3"),
            ("unit_price", "REAL", "Y", "Price at order time, INR"),
            ("line_total", "REAL", "Y", "Derived: quantity * unit_price"),
        ]),
    "categories": dict(
        desc="Reference data. 10 complaint categories with default severity and owning team.",
        rel="Category 1:N Complaint.",
        pk=["category_id"], unique=["category_name"], fks=[],
        fields=[
            ("category_id", "TEXT", "Y", "CAT-nn, unique"),
            ("category_name", "TEXT", "Y", "Unique"),
            ("default_severity", "TEXT", "Y", "Low | Medium | High | Critical"),
            ("owning_team", "TEXT", "Y", "Team that owns this category"),
            ("is_active", "BOOL", "Y", "0/1"),
            ("effective_from", "DATE", "Y", "YYYY-MM-DD"),
            ("effective_to", "DATE", "N", "Blank = still effective"),
        ]),
    "priority_rules": dict(
        desc="Reference data. Scoring rules used to decide priority. Each matching ADD_POINTS rule adds points; FORCE_P1 overrides everything.",
        rel="Applied by the rules engine (no foreign key). Effective-dated.",
        pk=["rule_id"], unique=[], fks=[],
        fields=[
            ("rule_id", "TEXT", "Y", "PR-nnn, unique"),
            ("factor", "TEXT", "Y", "is_safety_issue | sentiment_score | order_value | is_repeat | vulnerable_flag | severity_rank"),
            ("operator", "TEXT", "Y", "== | >= | <="),
            ("threshold", "REAL", "Y", "Number compared with the factor"),
            ("points", "INTEGER", "Y", "Points added when the rule matches (0 for FORCE_P1)"),
            ("effect", "TEXT", "Y", "ADD_POINTS | FORCE_P1"),
            ("effective_from", "DATE", "Y", "YYYY-MM-DD"),
            ("effective_to", "DATE", "N", "Blank = still effective"),
        ]),
    "priority_levels": dict(
        desc="Reference data. The 4 priority levels with SLA hours, queue and escalation threshold.",
        rel="Priority level 1:N Complaint, 1:N SLAClock.",
        pk=["priority_level"], unique=[], fks=[],
        fields=[
            ("priority_level", "TEXT", "Y", "P1 | P2 | P3 | P4"),
            ("min_points", "INTEGER", "Y", "Minimum rule points needed for this level"),
            ("sla_hours", "INTEGER", "Y", "Hours allowed to resolve"),
            ("queue", "TEXT", "Y", "Queue name the complaint must be placed in"),
            ("escalation_pct", "REAL", "Y", "Escalate when working time passes this share of sla_hours"),
        ]),
    "agents": dict(
        desc="Reference data. Synthetic support agents, 5 per team.",
        rel="Agent 1:N Assignment.",
        pk=["agent_id"], unique=[], fks=[],
        fields=[
            ("agent_id", "TEXT", "Y", "AGT-nnn, unique"),
            ("agent_name", "TEXT", "Y", "Synthetic"),
            ("team", "TEXT", "Y", "Logistics | Product Quality | Billing & Refunds | Customer Care | Safety & Compliance | Escalations"),
        ]),
    "complaints": dict(
        desc="Transaction. One row per complaint. category/severity/priority are the SYSTEM decisions (made from the complaint text and the rules).",
        rel="Customer 1:N Complaint; Order 1:N Complaint; Product 1:N Complaint; Complaint self-link (optional) for repeats.",
        pk=["complaint_id"], unique=[],
        fks=[("customer_id", "customers", "customer_id"), ("order_id", "orders", "order_id"),
             ("product_id", "products", "product_id"), ("category_id", "categories", "category_id"),
             ("priority_level", "priority_levels", "priority_level"),
             ("repeat_of_complaint_id", "complaints", "complaint_id")],
        fields=[
            ("complaint_id", "TEXT", "Y", "CMP-2026-nnnnnn, unique, numbered in created_at order"),
            ("customer_id", "TEXT", "Y", "FK customers (the 'complaint without customer' test case breaks this on purpose)"),
            ("order_id", "TEXT", "Y", "FK orders"),
            ("product_id", "TEXT", "Y", "FK products; must be an item of the order"),
            ("channel", "TEXT", "Y", "Email | Phone | Web Form | Mobile App | Social Media | Chat"),
            ("category_id", "TEXT", "Y", "FK categories (assigned by keyword classifier)"),
            ("severity", "TEXT", "Y", "Low | Medium | High | Critical (= category default severity)"),
            ("sentiment_score", "REAL", "Y", "-1.0 to 1.0, from a word lexicon on the first message"),
            ("is_safety_issue", "BOOL", "Y", "1 when category is Product Safety"),
            ("is_repeat", "BOOL", "Y", "1 when same customer+product+category complained in the previous 30 days"),
            ("repeat_of_complaint_id", "TEXT", "N", "FK complaints; the previous matching complaint"),
            ("vulnerable_flag", "BOOL", "Y", "Copied from customer when the complaint was created"),
            ("order_value", "REAL", "Y", "Copied from orders.order_total"),
            ("priority_level", "TEXT", "Y", "P1-P4, derived from priority_rules"),
            ("created_at", "DATETIME", "Y", "YYYY-MM-DD HH:MM:SS, not after the data cut-off"),
            ("current_status", "TEXT", "Y", "Derived: to_status of the last status event"),
        ]),
    "complaint_status_events": dict(
        desc="Event log. Append-only status history; nothing is overwritten.",
        rel="Complaint 1:N status events.",
        pk=["event_id"], unique=[], fks=[("complaint_id", "complaints", "complaint_id")],
        fields=[
            ("event_id", "TEXT", "Y", "EVT-<complaint-id>-nnn"),
            ("complaint_id", "TEXT", "Y", "FK complaints"),
            ("from_status", "TEXT", "N", "Blank only for the first event"),
            ("to_status", "TEXT", "Y", "NEW | ASSIGNED | IN_PROGRESS | WAITING_CUSTOMER | ESCALATED | RESOLVED | CLOSED | REOPENED"),
            ("event_time", "DATETIME", "Y", "Never earlier than the previous event"),
            ("actor_type", "TEXT", "Y", "SYSTEM | AGENT | CUSTOMER"),
            ("note", "TEXT", "Y", "Short description"),
        ]),
    "complaint_messages": dict(
        desc="Customer communication log (customer, agent and system messages).",
        rel="Complaint 1:N ComplaintMessage.",
        pk=["message_id"], unique=[], fks=[("complaint_id", "complaints", "complaint_id")],
        fields=[
            ("message_id", "TEXT", "Y", "MSG-<complaint-id>-nnn, numbered in sent_at order"),
            ("complaint_id", "TEXT", "Y", "FK complaints"),
            ("sender_type", "TEXT", "Y", "CUSTOMER | AGENT | SYSTEM"),
            ("message_kind", "TEXT", "Y", "CUSTOMER_COMPLAINT | AGENT_ACK | AGENT_INFO_REQUEST | CUSTOMER_REPLY | SYSTEM_ESCALATION_NOTICE | AGENT_UPDATE | AGENT_RESOLUTION_NOTICE | SYSTEM_CLOSURE_NOTICE | CUSTOMER_REOPEN_REQUEST"),
            ("channel", "TEXT", "Y", "Same as the complaint channel"),
            ("sent_at", "DATETIME", "Y", "Not before complaint created_at"),
            ("message_text", "TEXT", "Y", "Synthetic text"),
        ]),
    "assignments": dict(
        desc="Ownership history. A new row is added at every hand-over; old rows are closed, never edited away.",
        rel="Complaint 1:N Assignment; Agent 1:N Assignment.",
        pk=["assignment_id"], unique=[],
        fks=[("complaint_id", "complaints", "complaint_id"), ("agent_id", "agents", "agent_id")],
        fields=[
            ("assignment_id", "TEXT", "Y", "ASG-<complaint-id>-nn"),
            ("complaint_id", "TEXT", "Y", "FK complaints"),
            ("agent_id", "TEXT", "Y", "FK agents"),
            ("team", "TEXT", "Y", "Team of the agent"),
            ("queue", "TEXT", "Y", "P1-URGENT | P2-HIGH | P3-STANDARD | P4-LOW | ESCALATION"),
            ("reason", "TEXT", "Y", "INITIAL | ESCALATION | REOPEN"),
            ("assigned_at", "DATETIME", "Y", "Start of ownership"),
            ("ended_at", "DATETIME", "N", "Equals the next assignment's assigned_at; blank for the current owner"),
            ("is_current", "BOOL", "Y", "Exactly one current row per complaint"),
        ]),
    "sla_clocks": dict(
        desc="One SLA clock per complaint. Deadline = start + sla_hours + paused hours.",
        rel="Complaint 1:1 SLAClock.",
        pk=["sla_id"], unique=["complaint_id"],
        fks=[("complaint_id", "complaints", "complaint_id"), ("priority_level", "priority_levels", "priority_level")],
        fields=[
            ("sla_id", "TEXT", "Y", "SLA-<complaint-id>"),
            ("complaint_id", "TEXT", "Y", "FK complaints, unique"),
            ("priority_level", "TEXT", "Y", "Same as the complaint priority"),
            ("sla_hours", "INTEGER", "Y", "From priority_levels"),
            ("started_at", "DATETIME", "Y", "Equals complaint created_at"),
            ("paused_hours", "REAL", "Y", "Derived: total hours spent in WAITING_CUSTOMER"),
            ("pause_count", "INTEGER", "Y", "Number of WAITING_CUSTOMER events"),
            ("deadline_at", "DATETIME", "Y", "started_at + sla_hours + paused_hours"),
            ("stopped_at", "DATETIME", "N", "Time of the first RESOLVED event"),
            ("escalated_at", "DATETIME", "N", "Time of the ESCALATED event"),
            ("is_breached", "BOOL", "Y", "1 if stopped_at (or the data cut-off if still open) is after deadline_at"),
        ]),
    "resolutions": dict(
        desc="Outcome of a complaint. Created at the first RESOLVED event; kept up to date if the complaint is reopened (history stays in the events).",
        rel="Complaint 1:1 Resolution (optional).",
        pk=["resolution_id"], unique=["complaint_id"],
        fks=[("complaint_id", "complaints", "complaint_id"), ("resolved_by_agent_id", "agents", "agent_id")],
        fields=[
            ("resolution_id", "TEXT", "Y", "RES-<complaint-id>"),
            ("complaint_id", "TEXT", "Y", "FK complaints, unique"),
            ("resolution_type", "TEXT", "Y", "REFUND | REPLACEMENT | REPAIR | CREDIT | APOLOGY_EXPLANATION"),
            ("refund_amount", "REAL", "Y", "INR, 0 when nothing is paid"),
            ("refund_status", "TEXT", "Y", "NOT_APPLICABLE | PENDING | PAID"),
            ("first_resolved_at", "DATETIME", "Y", "Equals first RESOLVED event; must not be before complaint created_at"),
            ("resolved_at", "DATETIME", "Y", "Equals last RESOLVED event"),
            ("reopen_count", "INTEGER", "Y", "Equals number of REOPENED events"),
            ("resolved_by_agent_id", "TEXT", "Y", "Owner at the last RESOLVED event"),
        ]),
    "surveys": dict(
        desc="Post-resolution survey, sent after the complaint is closed.",
        rel="Complaint 1:1 Survey (optional).",
        pk=["survey_id"], unique=["complaint_id"], fks=[("complaint_id", "complaints", "complaint_id")],
        fields=[
            ("survey_id", "TEXT", "Y", "SVY-<complaint-id>"),
            ("complaint_id", "TEXT", "Y", "FK complaints, unique"),
            ("sent_at", "DATETIME", "Y", "Must be on/after the final CLOSED event"),
            ("responded_at", "DATETIME", "N", "Blank = no response"),
            ("csat_score", "INTEGER", "N", "1 to 5, blank when no response"),
        ]),
}

GROUND_TRUTH_FIELDS = [
    "complaint_id", "true_category_id", "expected_priority_level", "expected_team",
    "expected_sla_hours", "expected_escalation", "scenario", "issue_type",
    "affected_entity", "affected_record_id", "issue_note"]


def schema_sql():
    """CREATE TABLE statements built from TABLES."""
    out = []
    for name, t in TABLES.items():
        cols = []
        for fname, ftype, req, _ in t["fields"]:
            cols.append(f"  {fname} {SQL_TYPES[ftype]}" + (" NOT NULL" if req == "Y" else ""))
        cols.append(f"  PRIMARY KEY ({', '.join(t['pk'])})")
        for u in t["unique"]:
            cols.append(f"  UNIQUE ({u})")
        for col, rt, rc in t["fks"]:
            cols.append(f"  FOREIGN KEY ({col}) REFERENCES {rt}({rc})")
        out.append(f"CREATE TABLE {name} (\n" + ",\n".join(cols) + "\n);")
    return "\n\n".join(out) + "\n"


def data_dictionary_md():
    lines = ["# Data dictionary", "",
             "Generated from `schema_spec.py` - do not edit by hand.", "",
             "Dates are `YYYY-MM-DD`, timestamps are `YYYY-MM-DD HH:MM:SS` (no time zone), booleans are 0/1, money is INR.", ""]
    for name, t in TABLES.items():
        lines += [f"## {name}", "", t["desc"], "",
                  f"- **Primary key:** {', '.join(t['pk'])}",
                  f"- **Relationships / cardinality:** {t['rel']}"]
        if t["fks"]:
            lines.append("- **Foreign keys:** " + "; ".join(f"{c} -> {rt}.{rc}" for c, rt, rc in t["fks"]))
        if t["unique"]:
            lines.append("- **Unique:** " + ", ".join(t["unique"]))
        lines += ["", "| Field | Type | Required | Allowed values / validation |", "|---|---|---|---|"]
        for fname, ftype, req, rule in t["fields"]:
            lines.append(f"| {fname} | {ftype} | {req} | {rule} |")
        lines.append("")
    lines += [
        "## ground_truth (kept in a separate folder, never an input feature)", "",
        "One row per complaint: `" + "`, `".join(GROUND_TRUTH_FIELDS) + "`.", "",
        "- `true_category_id`, `expected_priority_level`, `expected_team`, `expected_sla_hours`, `expected_escalation` are the correct decisions computed from the TRUE (not classifier) attributes.",
        "- `scenario` is NORMAL or a boundary case (BOUNDARY_ON_DEADLINE, BOUNDARY_AT_ESCALATION_THRESHOLD).",
        "- `issue_type`, `affected_entity`, `affected_record_id`, `issue_note` are filled only for deliberately injected anomalies.", "",
        "## Lifecycle", "",
        "`NEW -> ASSIGNED -> IN_PROGRESS -> (WAITING_CUSTOMER -> IN_PROGRESS)* -> [ESCALATED] -> RESOLVED -> CLOSED -> (REOPENED -> IN_PROGRESS -> RESOLVED -> CLOSED)`", ""]
    return "\n".join(lines)
