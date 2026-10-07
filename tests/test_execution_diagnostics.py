"""Read-only diagnostics exercise the CLI and real SQLite snapshots."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

import pytest

from domain.order import OrderStatus as S
from persistence.database import Database
from persistence.repositories import OrderRepository
from tests.test_order_engine import prepare

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'check_execution_state.py'


def invoke(path, cwd=None):
    result = subprocess.run([sys.executable, str(SCRIPT), '--db', str(path)], cwd=cwd,
                            capture_output=True, text=True, timeout=10)
    return result.returncode, json.loads(result.stdout)


def logical_snapshot(path):
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as conn:
        return '\n'.join(conn.iterdump())


def test_cli_reports_counts_without_writing_or_disclosing_account_payloads(tmp_path):
    path = tmp_path / 'execution # 中文.sqlite3'
    repo = OrderRepository(Database(path))
    unknown = prepare(repo, 'secret-intent-one')
    repo.claim_submission(unknown.order_id)
    repo.transition(unknown.order_id, S.UNKNOWN)
    prepare(repo, 'secret-intent-two')
    with repo.db.transaction() as conn:
        conn.execute("UPDATE trading_control SET state='HALTED'")
        conn.execute('UPDATE reconciliation_jobs SET due_at=?, lease_until=?', (time.time() - 100, 0))
    before = (path.read_bytes(), path.stat().st_mtime_ns, logical_snapshot(path))
    code, report = invoke(path, cwd=tmp_path)
    assert code == 0 and report['ok'] is True
    assert report['order_status_counts'] == {'APPROVED': 1, 'UNKNOWN': 1}
    assert report['reconciliation_jobs'] == {'total': 1, 'due_unleased': 1, 'leased': 0}
    assert report['trading_control'] == 'HALTED'
    assert report['event_counts']['order_events'] == len(repo.events(unknown.order_id)) + 4
    assert report['attention'] == ['UNKNOWN_ORDERS', 'RECONCILIATION_BACKLOG']
    assert 'VRTC1' not in json.dumps(report) and 'secret-intent' not in json.dumps(report)
    assert (path.read_bytes(), path.stat().st_mtime_ns, logical_snapshot(path)) == before


def test_missing_db_does_not_create_a_file_or_parent_directory(tmp_path):
    path = tmp_path / 'absent-directory' / 'absent.sqlite3'
    code, report = invoke(path)
    assert code == 2 and report['code'] == 'DATABASE_MISSING'
    assert not path.parent.exists()


def test_cli_reports_a_symlink_loop_as_a_controlled_error(tmp_path):
    path = tmp_path / 'loop.sqlite3'
    path.symlink_to(path.name)
    result = subprocess.run([sys.executable, str(SCRIPT), '--db', str(path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and result.stderr == ''
    report = json.loads(result.stdout)
    assert report['ok'] is False and report['code'] == 'DATABASE_UNREADABLE'
    assert str(path) not in result.stdout
    assert path.is_symlink() and path.readlink() == Path(path.name)


@pytest.mark.parametrize('case', ['corrupt', 'empty', 'old', 'future', 'missing_table', 'missing_column'])
def test_cli_refuses_corrupt_or_unsupported_schema_without_migration(tmp_path, case):
    path = tmp_path / 'fixture.sqlite3'
    if case == 'corrupt':
        path.write_bytes(b'not a SQLite database')
    elif case == 'empty':
        sqlite3.connect(path).close()
    else:
        Database(path)
        with sqlite3.connect(path) as conn:
            if case == 'old':
                conn.execute('DELETE FROM execution_schema_migrations WHERE version=3')
            elif case == 'future':
                conn.execute('INSERT INTO execution_schema_migrations VALUES(4)')
            elif case == 'missing_table':
                conn.execute('DROP TABLE risk_events')
            else:
                conn.execute('ALTER TABLE reconciliation_jobs DROP COLUMN lease_token')
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    code, report = invoke(path)
    assert code == 2 and report['ok'] is False
    assert report['code'] == ('DATABASE_UNREADABLE' if case == 'corrupt' else 'SCHEMA_UNSUPPORTED')
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_cli_reads_uncheckpointed_wal_instead_of_stale_main_database(tmp_path):
    path = tmp_path / 'wal.sqlite3'
    repo = OrderRepository(Database(path))
    order = prepare(repo)
    with sqlite3.connect(path) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("UPDATE orders SET status='UNKNOWN' WHERE order_id=?", (order.order_id,))
        writer.commit()
        assert Path(str(path) + '-wal').stat().st_size > 0
        main_before = (path.read_bytes(), path.stat().st_mtime_ns)
        dump_before = logical_snapshot(path)
        code, report = invoke(path)
        assert code == 0 and report['order_status_counts'] == {'UNKNOWN': 1}
        assert 'UNKNOWN_ORDERS' in report['attention']
        assert (path.read_bytes(), path.stat().st_mtime_ns) == main_before
        assert logical_snapshot(path) == dump_before


def test_cli_rejects_invalid_control_without_exposing_the_stored_value(tmp_path):
    path = tmp_path / 'invalid.sqlite3'
    Database(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE trading_control SET state='secret-invalid-control'")
    code, report = invoke(path)
    assert code == 2 and report['code'] == 'STATE_INVALID'
    assert 'secret-invalid-control' not in json.dumps(report)
