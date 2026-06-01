#!/usr/bin/env python3
"""Print the live FastAPI OpenAPI JSON.

This is useful if you deploy the service and want to compare it with the curated
schemas under examples/.
"""
import sys
from pathlib import Path as _Path

_PROJECT_ROOT = _Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import json

from app.main import app

print(json.dumps(app.openapi(), ensure_ascii=False, indent=2))
