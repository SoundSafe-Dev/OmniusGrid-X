"""Config bundle parsing for edge-agent collector configuration."""

import json
from typing import Any, Dict, List

import yaml


def collectors_from_bundle(bundle: bytes) -> List[Dict[str, Any]]:
    text = bundle.decode("utf-8")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = yaml.safe_load(text)

    if isinstance(parsed, list):
        collectors = parsed
    elif isinstance(parsed, dict):
        collectors = parsed.get("collectors")
    else:
        collectors = None

    if not isinstance(collectors, list):
        raise ValueError("config bundle must contain a collectors list")
    if not all(isinstance(collector, dict) for collector in collectors):
        raise ValueError("config bundle collectors must be objects")

    return collectors
