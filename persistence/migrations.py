"""Additive, transactional SQLite schema upgrades. Existing history stays intact."""
MIGRATIONS = {
    1: [
        """CREATE TABLE IF NOT EXISTS trade_intents (
            intent_id TEXT PRIMARY KEY, source TEXT NOT NULL, action TEXT NOT NULL,
            symbol TEXT NOT NULL, direction TEXT, amount TEXT NOT NULL, duration INTEGER NOT NULL,
            duration_unit TEXT NOT NULL, account_mode TEXT NOT NULL, created_at TEXT NOT NULL,
            raw_payload TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL UNIQUE REFERENCES trade_intents(intent_id),
            idempotency_key TEXT NOT NULL UNIQUE, account_id TEXT NOT NULL, status TEXT NOT NULL,
            symbol TEXT NOT NULL, direction TEXT, amount TEXT NOT NULL, contract_id INTEGER,
            transaction_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            last_error TEXT, lease_until REAL NOT NULL DEFAULT 0, data_json TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS order_events (
            event_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
            previous_status TEXT, new_status TEXT NOT NULL, event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL, payload_json TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS order_receipts (
            order_id TEXT PRIMARY KEY REFERENCES orders(order_id), account_id TEXT NOT NULL,
            transaction_id INTEGER, receipt_json TEXT NOT NULL, UNIQUE(account_id, transaction_id))""",
        """CREATE TABLE IF NOT EXISTS reconciliation_jobs (
            order_id TEXT PRIMARY KEY REFERENCES orders(order_id), attempts INTEGER NOT NULL DEFAULT 0,
            due_at REAL NOT NULL DEFAULT 0, lease_until REAL NOT NULL DEFAULT 0, last_error TEXT)""",
        """CREATE TABLE IF NOT EXISTS approvals (
            approval_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL REFERENCES trade_intents(intent_id),
            account_id TEXT NOT NULL, fingerprint TEXT NOT NULL, data_json TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS risk_events (
            event_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL, order_id TEXT NOT NULL,
            allowed INTEGER NOT NULL, code TEXT NOT NULL, reason TEXT NOT NULL,
            metrics TEXT NOT NULL, timestamp TEXT NOT NULL)""",
        "CREATE TABLE IF NOT EXISTS trading_control (singleton INTEGER PRIMARY KEY CHECK(singleton=1), state TEXT NOT NULL)",
        "INSERT OR IGNORE INTO trading_control VALUES(1, 'ENABLED')",
        "CREATE TRIGGER IF NOT EXISTS order_events_no_update BEFORE UPDATE ON order_events BEGIN SELECT RAISE(ABORT, 'append only'); END",
        "CREATE TRIGGER IF NOT EXISTS order_events_no_delete BEFORE DELETE ON order_events BEGIN SELECT RAISE(ABORT, 'append only'); END",
    ],
    2: [
        'ALTER TABLE orders ADD COLUMN owner_pid INTEGER',
        'ALTER TABLE reconciliation_jobs ADD COLUMN owner_pid INTEGER',
    ],
    3: ['ALTER TABLE reconciliation_jobs ADD COLUMN lease_token TEXT'],
}


def migrate(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS execution_schema_migrations (version INTEGER PRIMARY KEY)")
    versions = {row[0] for row in conn.execute("SELECT version FROM execution_schema_migrations")}
    for version, statements in sorted(MIGRATIONS.items()):
        if version not in versions:
            for statement in statements:
                conn.execute(statement)
            conn.execute("INSERT INTO execution_schema_migrations VALUES(?)", (version,))
