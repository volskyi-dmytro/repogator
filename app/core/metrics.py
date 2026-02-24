import time
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

# --- Counters ---
webhook_events_total = Counter(
    "repogator_webhook_events_total",
    "Total webhook events received",
    ["event_type", "action", "repo"]
)

agent_runs_total = Counter(
    "repogator_agent_runs_total",
    "Total agent runs",
    ["agent_name", "status"]
)

github_api_calls_total = Counter(
    "repogator_github_api_calls_total",
    "Total GitHub API calls",
    ["endpoint", "status_code"]
)

# --- Histograms ---
agent_duration_seconds = Histogram(
    "repogator_agent_duration_seconds",
    "Agent processing time in seconds",
    ["agent_name"],
    buckets=[1, 5, 10, 30, 60, 120, 300]
)

webhook_queue_wait_seconds = Histogram(
    "repogator_webhook_queue_wait_seconds",
    "Time events spend waiting in Redis queue",
    buckets=[0.1, 0.5, 1, 5, 10, 30, 60]
)

# --- Gauges ---
queue_depth = Gauge(
    "repogator_queue_depth",
    "Current number of events in Redis queue"
)

active_users = Gauge(
    "repogator_active_users_total",
    "Total registered users"
)

tracked_repos = Gauge(
    "repogator_tracked_repos_total",
    "Total active tracked repositories"
)

knowledge_documents = Gauge(
    "repogator_knowledge_documents_total",
    "Total knowledge base documents",
    ["collection_type"]
)
