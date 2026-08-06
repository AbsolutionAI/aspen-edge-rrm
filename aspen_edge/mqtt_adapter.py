"""MQTT-first edge adapter (BEL-190 / BEL-115).

Default: in-process broker stub.
Optional live broker: ASPEN_MQTT_HOST[, ASPEN_MQTT_PORT] + paho-mqtt.
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
    _subs: dict[str, list[Handler]] = field(default_factory=lambda: defaultdict(list))
    messages: list[tuple[str, dict]] = field(default_factory=list)

    def publish(self, topic: str, payload: dict) -> None:
        self.messages.append((topic, payload))
        for h in list(self._subs.get(topic, [])):
            h(topic, payload)
        for pat, handlers in list(self._subs.items()):
            if pat.endswith("/#"):
                prefix = pat[:-2]
                if topic.startswith(prefix):
                    for h in handlers:
                        h(topic, payload)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    def loop_start(self) -> None:
        return None

    def loop_stop(self) -> None:
        return None


class PahoMQTT:
    """Thin paho wrapper exposing publish/subscribe(topic, handler)."""

    def __init__(self, host: str, port: int = 1883, client_id: str | None = None):
        import paho.mqtt.client as mqtt

        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self.messages: list[tuple[str, dict]] = []
        self._mqtt = mqtt
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id or f"aspen-edge-{uuid.uuid4().hex[:8]}",
        )
        self._client.on_message = self._on_message
        self._host = host
        self._port = port

    def _on_message(self, client, userdata, msg):  # noqa: ANN001
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            payload = {"raw": msg.payload.decode(errors="replace")}
        topic = msg.topic
        self.messages.append((topic, payload))
        for h in list(self._handlers.get(topic, [])):
            h(topic, payload)
        for pat, handlers in list(self._handlers.items()):
            if pat.endswith("/#") and topic.startswith(pat[:-2]):
                for h in handlers:
                    h(topic, payload)

    def connect(self) -> None:
        self._client.connect(self._host, self._port, 60)

    def loop_start(self) -> None:
        self._client.loop_start()

    def loop_stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def publish(self, topic: str, payload: dict) -> None:
        self._client.publish(topic, json.dumps(payload))
        self.messages.append((topic, payload))

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._handlers[topic].append(handler)
        # paho wildcard: replace /# with /#
        self._client.subscribe(topic if not topic.endswith("/#") else topic[:-1] + "#")


@dataclass
class MQTTEdgeAdapter:
    node_id: str
    prefix: str = "aspen/edge"
    client: Any = None
    _last_sense: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = InMemoryMQTT()
        self.client.subscribe(f"{self.prefix}/{self.node_id}/sensor/#", self._on_sensor)

    def _on_sensor(self, topic: str, payload: dict) -> None:
        name = topic.rstrip("/").split("/")[-1]
        self._last_sense[name] = payload.get("value", payload)

    def publish_sensor(self, name: str, value: Any) -> None:
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

    def start(self) -> None:
        if hasattr(self.client, "loop_start"):
            self.client.loop_start()

    def stop(self) -> None:
        if hasattr(self.client, "loop_stop"):
            self.client.loop_stop()

    @staticmethod
    def from_env(node_id: str) -> "MQTTEdgeAdapter":
        host = os.environ.get("ASPEN_MQTT_HOST")
        if not host:
            return MQTTEdgeAdapter(node_id=node_id)
        port = int(os.environ.get("ASPEN_MQTT_PORT", "1883"))
        try:
            client = PahoMQTT(host, port, client_id=f"aspen-{node_id}")
            client.connect()
        except ImportError as e:
            raise RuntimeError("paho-mqtt required when ASPEN_MQTT_HOST set") from e
        adapter = MQTTEdgeAdapter(node_id=node_id, client=client)
        adapter.start()
        return adapter
