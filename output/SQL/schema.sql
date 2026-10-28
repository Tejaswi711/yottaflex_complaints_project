CREATE TABLE customers (
  customer_id TEXT NOT NULL,
  full_name TEXT NOT NULL,
  email TEXT NOT NULL,
  city TEXT NOT NULL,
  segment TEXT NOT NULL,
  vulnerable_flag INTEGER NOT NULL,
  signup_date TEXT NOT NULL,
  PRIMARY KEY (customer_id),
  UNIQUE (email)
);

CREATE TABLE products (
  product_id TEXT NOT NULL,
  product_name TEXT NOT NULL,
  product_category TEXT NOT NULL,
  unit_price REAL NOT NULL,
  is_hazard_prone INTEGER NOT NULL,
  PRIMARY KEY (product_id)
);

CREATE TABLE orders (
  order_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  order_date TEXT NOT NULL,
  promised_date TEXT NOT NULL,
  delivered_date TEXT,
  delivery_status TEXT NOT NULL,
  order_channel TEXT NOT NULL,
  order_total REAL NOT NULL,
  PRIMARY KEY (order_id),
  FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_items (
  order_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  quantity INTEGER NOT NULL,
  unit_price REAL NOT NULL,
  line_total REAL NOT NULL,
  PRIMARY KEY (order_id, product_id),
  FOREIGN KEY (order_id) REFERENCES orders(order_id),
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE categories (
  category_id TEXT NOT NULL,
  category_name TEXT NOT NULL,
  default_severity TEXT NOT NULL,
  owning_team TEXT NOT NULL,
  is_active INTEGER NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  PRIMARY KEY (category_id),
  UNIQUE (category_name)
);

CREATE TABLE priority_rules (
  rule_id TEXT NOT NULL,
  factor TEXT NOT NULL,
  operator TEXT NOT NULL,
  threshold REAL NOT NULL,
  points INTEGER NOT NULL,
  effect TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  PRIMARY KEY (rule_id)
);

CREATE TABLE priority_levels (
  priority_level TEXT NOT NULL,
  min_points INTEGER NOT NULL,
  sla_hours INTEGER NOT NULL,
  queue TEXT NOT NULL,
  escalation_pct REAL NOT NULL,
  PRIMARY KEY (priority_level)
);

CREATE TABLE agents (
  agent_id TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  team TEXT NOT NULL,
  PRIMARY KEY (agent_id)
);

CREATE TABLE complaints (
  complaint_id TEXT NOT NULL,
  customer_id TEXT NOT NULL,
  order_id TEXT NOT NULL,
  product_id TEXT NOT NULL,
  channel TEXT NOT NULL,
  category_id TEXT NOT NULL,
  severity TEXT NOT NULL,
  sentiment_score REAL NOT NULL,
  is_safety_issue INTEGER NOT NULL,
  is_repeat INTEGER NOT NULL,
  repeat_of_complaint_id TEXT,
  vulnerable_flag INTEGER NOT NULL,
  order_value REAL NOT NULL,
  priority_level TEXT NOT NULL,
  created_at TEXT NOT NULL,
  current_status TEXT NOT NULL,
  PRIMARY KEY (complaint_id),
  FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
  FOREIGN KEY (order_id) REFERENCES orders(order_id),
  FOREIGN KEY (product_id) REFERENCES products(product_id),
  FOREIGN KEY (category_id) REFERENCES categories(category_id),
  FOREIGN KEY (priority_level) REFERENCES priority_levels(priority_level),
  FOREIGN KEY (repeat_of_complaint_id) REFERENCES complaints(complaint_id)
);

CREATE TABLE complaint_status_events (
  event_id TEXT NOT NULL,
  complaint_id TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  event_time TEXT NOT NULL,
  actor_type TEXT NOT NULL,
  note TEXT NOT NULL,
  PRIMARY KEY (event_id),
  FOREIGN KEY (complaint_id) REFERENCES complaints(complaint_id)
);

CREATE TABLE complaint_messages (
  message_id TEXT NOT NULL,
  complaint_id TEXT NOT NULL,
  sender_type TEXT NOT NULL,
  message_kind TEXT NOT NULL,
  channel TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  message_text TEXT NOT NULL,
  PRIMARY KEY (message_id),
  FOREIGN KEY (complaint_id) REFERENCES complaints(complaint_id)
);

CREATE TABLE assignments (
  assignment_id TEXT NOT NULL,
  complaint_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  team TEXT NOT NULL,
  queue TEXT NOT NULL,
  reason TEXT NOT NULL,
  assigned_at TEXT NOT NULL,
  ended_at TEXT,
  is_current INTEGER NOT NULL,
  PRIMARY KEY (assignment_id),
  FOREIGN KEY (complaint_id) REFERENCES complaints(complaint_id),
  FOREIGN KEY (agent_id) REFERENCES agents(agent_id)
);

CREATE TABLE sla_clocks (
  sla_id TEXT NOT NULL,
  complaint_id TEXT NOT NULL,
  priority_level TEXT NOT NULL,
  sla_hours INTEGER NOT NULL,
  started_at TEXT NOT NULL,
  paused_hours REAL NOT NULL,
  pause_count INTEGER NOT NULL,
  deadline_at TEXT NOT NULL,
  stopped_at TEXT,
  escalated_at TEXT,
  is_breached INTEGER NOT NULL,
  PRIMARY KEY (sla_id),
  UNIQUE (complaint_id),
  FOREIGN KEY (complaint_id) REFERENCES complaints(complaint_id),
  FOREIGN KEY (priority_level) REFERENCES priority_levels(priority_level)
);

CREATE TABLE resolutions (
  resolution_id TEXT NOT NULL,
  complaint_id TEXT NOT NULL,
  resolution_type TEXT NOT NULL,
  refund_amount REAL NOT NULL,
  refund_status TEXT NOT NULL,
  first_resolved_at TEXT NOT NULL,
  resolved_at TEXT NOT NULL,
  reopen_count INTEGER NOT NULL,
  resolved_by_agent_id TEXT NOT NULL,
  PRIMARY KEY (resolution_id),
  UNIQUE (complaint_id),
  FOREIGN KEY (complaint_id) REFERENCES complaints(complaint_id),
  FOREIGN KEY (resolved_by_agent_id) REFERENCES agents(agent_id)
);

CREATE TABLE surveys (
  survey_id TEXT NOT NULL,
  complaint_id TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  responded_at TEXT,
  csat_score INTEGER,
  PRIMARY KEY (survey_id),
  UNIQUE (complaint_id),
  FOREIGN KEY (complaint_id) REFERENCES complaints(complaint_id)
);
