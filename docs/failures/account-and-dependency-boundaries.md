# Account authorization and clean-install failures

Recorded during the 2026-09-16 audit; this documents current inspection and injected regression cases, not an observed real-account incident.

## Symptom and root cause

The UI execution worker saved `account_ok` but did not return when account lookup failed. An unknown account type also passed the backend demo/live gate. A failed preflight could therefore reach the execution tool; this does not prove an unauthorized broker trade succeeded, since the backend independently authorizes.

Separately, a clean `requirements.txt` install selected MCP 2.2.0, while `server.py` imports the v1 `mcp.server.fastmcp.FastMCP` API. Pytest stopped with six collection errors and `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`.

## Reproduction

`tests/test_failure_boundaries.py` injects a failed account response and an unknown account response into the real UI execution worker, asserting that only the account lookup runs. It also exercises the backend unknown-account gate, malformed manager dispatch, failed proposal, ambiguous buy timeout and a transient advisor-node exception.

The installation failure is reproducible with MCP 2.2.0 against this v1 source. No network credentials or live account are required for these tests.

## Fix and validation

- Return `account_authorization_unverified` before UI execution on failed/unrecognized lookup.
- Reject unknown account types in the backend, even with live execution enabled.
- Reject non-object or missing-required-field manager arguments before worker dispatch.
- Constrain `mcp>=1.9.0,<2`; a v2 migration is separate work.

After installing MCP 1.30.0, `.venv/bin/python -m pytest -q` completed with **23 passed in 6.13s**. Ten added parameterized cases complement thirteen existing tests. Environment: local macOS arm64, Python 3.12; fake transport, synthetic market snapshots and no external trade execution. The advisor fallback case injects a one-time failure, not a persistent outage.

## Remaining risk

The API is still the authority on account authorization. Human confirmation is a configurable UI boundary and is not bound to an immutable signed order for direct MCP clients. A write timeout leaves an uncertain outcome; zero retries does not reconcile it. Model argument checks here are not full schema validation. Other dependency ranges remain open, so this run is evidence for the installed environment, not a guarantee for every future installation.
