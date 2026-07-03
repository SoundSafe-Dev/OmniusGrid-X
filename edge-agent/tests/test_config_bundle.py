import pytest

from opsgrid_agent.config_bundle import collectors_from_bundle


def test_config_bundle_loader_accepts_yaml_collectors():
    bundle = b"""
collectors:
  - asset_id: asset-1
    type: mqtt
    config:
      broker: localhost
"""

    collectors = collectors_from_bundle(bundle)

    assert collectors == [
        {
            "asset_id": "asset-1",
            "type": "mqtt",
            "config": {"broker": "localhost"},
        }
    ]


def test_config_bundle_loader_accepts_json_collectors_list():
    bundle = b'[{"asset_id":"asset-1","type":"modbus","config":{}}]'

    collectors = collectors_from_bundle(bundle)

    assert collectors == [{"asset_id": "asset-1", "type": "modbus", "config": {}}]


def test_config_bundle_loader_rejects_missing_collectors():
    with pytest.raises(ValueError, match="collectors list"):
        collectors_from_bundle(b'{"not_collectors":[]}')
