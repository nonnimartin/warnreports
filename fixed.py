from __future__ import annotations

import settings
import json

with open(settings.CONVERSIONS_FILE) as f:
    conversions: dict[str, dict[str, str]] = json.load(f)

states = conversions.keys()
