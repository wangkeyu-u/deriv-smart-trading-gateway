"""Print an MCP client configuration for this checkout and Python interpreter."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


project = Path(__file__).resolve().parents[1]
database=Path(os.getenv("DERIV_DB_PATH") or project/"local_data"/"gateway.sqlite3").expanduser()
database=(database if database.is_absolute() else project/database).resolve()
config = {
    "mcpServers": {
        "deriv-smart-trading-gateway": {
            "command": sys.executable,
            "args": [str(project / "server.py")],
            "env": {
                "DERIV_APP_ID": "1089",
                "DERIV_DB_PATH": str(database),
                "DERIV_WS_URL_TEMPLATE": "wss://ws.derivws.com/websockets/v3?app_id={app_id}",
            },
        }
    }
}
print(json.dumps(config, ensure_ascii=False, indent=2))
