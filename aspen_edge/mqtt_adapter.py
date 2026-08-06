"""MQTT-first edge adapter (BEL-190 / BEL-115).

Default: in-process broker stub so `make smoke` needs no mosquitto.
Optional: paho-mqtt if ASPEN_MQTT_HOST is set.
"""
from __future__ import annotations
import json
import os
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

Handler = Callable[[str, dict], None]


@dataclass
class InMemoryMQTT:
    """Minimal topic bus for lab tests."""
    _subs: dict[str, list[Handler]] = field(default_factory=lambda: defaultdict(list))
    messages: list[tuple[str, dict]] = field(default_factory=list)

    def publish(self, topic: str, payload: dict) -> None:
        self.messages.append((topic, payload))
        for h in list(self._subs.get(topic, [])):
            h(topic, payload)
        # wildcard suffix /#
        for pat, handlers in list(self._subs.items()):
            if pat.endswith("/#"):
                prefix = pat[:-2]
                if topic.startswith(prefix):
                    for h in handlers:
                        h(topic, payload)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)


@dataclass
class MQTTEdgeAdapter:
    """Bridges MQTT sensor topics → sense dicts; command topics out."""

    node_id: str
    prefix: str = "aspen/edge"
    client: Any = None
    _last_sense: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = InMemoryMQTT()
        self.client.subscribe(f"{self.prefix}/{self.node_id}/sensor/#", self._on_sensor)

    def _on_sensor(self, topic: str, payload: dict) -> None:
        # topic .../sensor/<name>
        name = topic.rstrip("/").split("/")[-1]
        self._last_sense[name] = payload.get("value", payload)

    def publish_sensor(self, name: str, value: Any) -> None:
        """Lab helper / device side."""
        self.client.publish(
            f"{self.prefix}/{self.node_id}/sensor/{name}",
            {"value": value, "ts": time.time(), "id": str(uuid.uuid4())},
        )

    def sense(self) -> dict:
        return dict(self._last_sense)

    def publish_command(self, skill: str, args: dict) -> None:
        self.client.publish(
            f"{self.prefix}/{self.node_id}/command",
            {"skill": skill, "args": args, "ts": time.time()},
        )

    @staticmethod
    def from_env(node_id: str) -> "MQTTEdgeAdapter":
        host = os.environ.get("ASPEN_MQTT_HOST")
        if not host:
            return MQTTEdgeAdapter(node_id=node_id)
        try:
            import paho.mqtt.client as mqtt  # type: ignore
        except ImportError as e:
            raise RuntimeError("paho-mqtt required when ASPEN_MQTT_HOST set") from e
        # Thin wrapper: connect and mirror into InMemory for same API surface in v0.1
        # Full paho loop integration is follow-up; document env for ops.
        raise NotImplementedError(
            "Live paho loop not in smoke path yet; use InMemory or contribute bridge"
        )
