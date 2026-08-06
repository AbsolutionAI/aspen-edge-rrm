"""Verify PahoMQTT class imports when paho installed (no broker required for import)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import paho.mqtt.client  # noqa
    from aspen_edge.mqtt_adapter import PahoMQTT
    print("paho class ok", PahoMQTT)
except ImportError:
    print("paho skip: not installed")
