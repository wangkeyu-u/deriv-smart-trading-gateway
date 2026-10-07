#!/usr/bin/env python3
"""Inspect an existing execution database without initializing or recovering it."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domain.order import OrderStatus
from persistence.database import DEFAULT_DB_PATH, resolve_database_path
from persistence.migrations import MIGRATIONS


class DiagnosticError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def inspect_database(path):
    """Return aggregate counts from one SQLite read transaction, including WAL."""
    try:
        path = resolve_database_path(path)
        exists = path.is_file()
    except (OSError, RuntimeError):
        raise DiagnosticError('DATABASE_UNREADABLE', 'Database path could not be resolved or accessed.') from None
    if not exists:
        raise DiagnosticError('DATABASE_MISSING', 'Existing database file required; nothing was created.')
    conn = None
    try:
        conn = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=3, isolation_level=None)
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        if conn.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise DiagnosticError('DATABASE_INVALID', 'SQLite quick_check failed.')
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {
            'execution_schema_migrations': {'version'},
            'trade_intents': {'intent_id'},
            'orders': {'status'},
            'order_events': {'event_id'},
            'order_receipts': {'order_id'},
            'reconciliation_jobs': {'due_at', 'lease_until', 'lease_token'},
            'approvals': {'approval_id'},
            'risk_events': {'event_id'},
            'trading_control': {'singleton', 'state'},
        }
        if not required.keys() <= tables:
            raise DiagnosticError('SCHEMA_UNSUPPORTED', 'Execution schema is incomplete; no migration was attempted.')
        for table, columns in required.items():
            # Table names are fixed above, never supplied by the command line.
            actual = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
            if not columns <= actual:
                raise DiagnosticError('SCHEMA_UNSUPPORTED', 'Execution schema is incomplete; no migration was attempted.')
        versions = [row[0] for row in conn.execute('SELECT version FROM execution_schema_migrations ORDER BY version')]
        if versions != sorted(MIGRATIONS):
            raise DiagnosticError('SCHEMA_UNSUPPORTED', 'Execution schema version is unsupported; no migration was attempted.')
        statuses = dict(conn.execute('SELECT status, count(*) FROM orders GROUP BY status ORDER BY status'))
        controls = conn.execute('SELECT singleton, state FROM trading_control').fetchall()
        valid_statuses = statuses.keys() <= {status.value for status in OrderStatus}
        valid_control = len(controls) == 1 and controls[0][0] == 1 and controls[0][1] in {'ENABLED', 'REDUCE_ONLY', 'HALTED'}
        if not valid_statuses or not valid_control:
            raise DiagnosticError('STATE_INVALID', 'Execution status or trading control is invalid.')
        now = time.time()
        jobs = conn.execute('SELECT count(*), COALESCE(sum(due_at <= ? AND lease_until <= ?), 0), COALESCE(sum(lease_until > ?), 0) FROM reconciliation_jobs', (now, now, now)).fetchone()
        attention = []
        if statuses.get('UNKNOWN', 0):
            attention.append('UNKNOWN_ORDERS')
        if jobs[0]:
            attention.append('RECONCILIATION_BACKLOG')
        return {
            'ok': True,
            'database': str(path),
            'schema_versions': versions,
            'trading_control': controls[0][1],
            'order_status_counts': statuses,
            'reconciliation_jobs': {'total': jobs[0], 'due_unleased': jobs[1], 'leased': jobs[2]},
            'event_counts': {
                'order_events': conn.execute('SELECT count(*) FROM order_events').fetchone()[0],
                'order_receipts': conn.execute('SELECT count(*) FROM order_receipts').fetchone()[0],
                'risk_events': conn.execute('SELECT count(*) FROM risk_events').fetchone()[0],
            },
            'attention': attention,
        }
    except sqlite3.Error:
        # Avoid exposing stored payloads or mistaking a locked/corrupt DB for an empty one.
        raise DiagnosticError('DATABASE_UNREADABLE', 'Database is locked, corrupt or unreadable; no recovery was attempted.') from None
    except OSError:
        raise DiagnosticError('DATABASE_UNREADABLE', 'Database could not be accessed; no recovery was attempted.') from None
    finally:
        if conn is not None:
            conn.close()  # Rolls back the read transaction; never commits application writes.


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=os.getenv('DERIV_DB_PATH') or DEFAULT_DB_PATH,
                        help='Existing DB; relative paths are anchored to the repository root.')
    args = parser.parse_args(argv)
    try:
        report = inspect_database(args.db)
    except DiagnosticError as error:
        print(json.dumps({'ok': False, 'code': error.code, 'message': str(error)}))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
