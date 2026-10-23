"""Bounded, opt-in capture of received Aruba application messages.

Only sanitized, known protobuf fields are retained. Original wire messages and
unparseable bodies must never be stored: they may contain access tokens.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from time import monotonic
from typing import Any

from google.protobuf.descriptor import FieldDescriptor
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError, Message

DEFAULT_TIMEOUT = 60
DEFAULT_MAX_BYTES = 1024 * 1024
MAX_TIMEOUT = 300
MIN_MAX_BYTES = 1024
MAX_MAX_BYTES = 10 * 1024 * 1024
_DEVICE_FIELDS = {
    "bleData": "mac",
    "reported": "mac",
    "results": "deviceMac",
    "characteristics": "deviceMac",
    "status": "deviceMac",
}


class PacketCapture:
    """One capture session per listener, confined to its asyncio event loop."""

    def __init__(self, *, telemetry_cls: type, access_token: str | None = None) -> None:
        self._telemetry_cls = telemetry_cls
        self._access_token = access_token
        self._timer: asyncio.TimerHandle | None = None
        self.clear()

    def start(
        self,
        *,
        device_mac: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> dict[str, Any]:
        self._expire()
        if self._active:
            raise ValueError("A packet capture is already running; stop it first")
        if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT:
            raise ValueError(f"timeout must be an integer between 1 and {MAX_TIMEOUT}")
        if type(max_bytes) is not int or not MIN_MAX_BYTES <= max_bytes <= MAX_MAX_BYTES:
            raise ValueError(
                f"max_bytes must be an integer between {MIN_MAX_BYTES} and {MAX_MAX_BYTES}"
            )
        normalized_mac = _normalize_mac(device_mac)
        loop = asyncio.get_running_loop()
        self.clear()
        self._device_mac = normalized_mac
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._started_at = _timestamp()
        self._deadline = monotonic() + timeout
        self._active = True
        self._timer = loop.call_later(timeout, self.stop, "timeout")
        return self.status()

    def stop(self, reason: str = "manual") -> dict[str, Any]:
        if self._active:
            self._active = False
            self._stopped_at = _timestamp()
            self._stop_reason = reason
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        return self.status()

    def clear(self) -> None:
        """Cancel capture and release retained messages on listener unload."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._active = False
        self._device_mac: str | None = None
        self._timeout = DEFAULT_TIMEOUT
        self._max_bytes = DEFAULT_MAX_BYTES
        self._started_at: str | None = None
        self._stopped_at: str | None = None
        self._stop_reason: str | None = None
        self._deadline = 0.0
        self._packets: list[str] = []
        self._bytes_used = 0
        self._dropped_packets = 0

    def status(self) -> dict[str, Any]:
        self._expire()
        return {
            "active": self._active,
            "started_at": self._started_at,
            "stopped_at": self._stopped_at,
            "stop_reason": self._stop_reason,
            "device_mac": self._device_mac,
            "timeout": self._timeout,
            "max_bytes": self._max_bytes,
            "bytes_used": self._bytes_used,
            "packet_count": len(self._packets),
            "dropped_packets": self._dropped_packets,
        }

    def export(self) -> dict[str, Any]:
        """Return an independent, JSON-safe snapshot without stopping capture."""
        return {
            "schema_version": 1,
            "byte_encoding": "base64",
            **self.status(),
            "packets": [json.loads(packet) for packet in self._packets],
        }

    def _expire(self) -> None:
        if self._active and monotonic() >= self._deadline:
            self.stop("timeout")

    def record_message(
        self,
        message: bytes | str,
        *,
        peer: str | None,
        connection_id: int,
        outcome: str = "received",
    ) -> None:
        self._expire()
        if not self._active:
            return
        telemetry = None
        if isinstance(message, bytes) and outcome == "received":
            telemetry = self._telemetry_cls()
            try:
                telemetry.ParseFromString(message)
            except DecodeError:
                outcome = "decode_error"
                telemetry = None

        if self._device_mac is not None:
            if telemetry is None or not _filter_device(telemetry, self._device_mac):
                return

        record: dict[str, Any] = {
            "timestamp": _timestamp(),
            "peer": _redact_text(peer, (self._access_token,)) if peer else peer,
            "connection_id": connection_id,
            "outcome": outcome,
            "message_type": "text" if isinstance(message, str) else "binary",
            "byte_length": len(message.encode("utf-8")) if isinstance(message, str) else len(message),
        }
        if telemetry is not None:
            telemetry.DiscardUnknownFields()
            secrets = {self._access_token} if self._access_token else set()
            _collect_secrets(telemetry, secrets)
            _sanitize(telemetry, secrets)
            reporter_mac = bytes(telemetry.reporter.mac)
            if len(reporter_mac) == 6:
                record["source"] = _redact_text(reporter_mac.hex(":").upper(), secrets)
            record["telemetry"] = MessageToDict(telemetry, preserving_proto_field_name=True)

        # Keeping compact JSON strings avoids unbounded Python object overhead
        # from tiny protobuf records. Include string allocation and conservative
        # list slot/overallocation overhead in the retained-memory budget.
        packet = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
        # The first append allocates four slots on CPython. Subsequent entries
        # amortize list growth with a deliberately conservative slot allowance.
        memory_bytes = sys.getsizeof(packet) + (32 if not self._packets else 16)
        if self._bytes_used + memory_bytes > self._max_bytes:
            self._dropped_packets += 1
            self.stop("memory_limit")
            return
        self._packets.append(packet)
        self._bytes_used += memory_bytes


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_mac(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("device_mac must be a Bluetooth MAC address")
    value = value.strip()
    if not value:
        return None
    if not re.fullmatch(r"(?:[0-9a-fA-F]{12}|(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}|(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2})", value):
        raise ValueError("device_mac must be a Bluetooth MAC address")
    return bytes.fromhex(value.replace(":", "").replace("-", "")).hex(":").upper()


def _filter_device(telemetry: Message, device_mac: str) -> bool:
    """Keep matching records only, even when Aruba batches several devices."""
    target = bytes.fromhex(device_mac.replace(":", ""))
    matched = False
    for descriptor, value in list(telemetry.ListFields()):
        field_name = descriptor.name
        mac_field = _DEVICE_FIELDS.get(field_name)
        if mac_field is not None:
            if descriptor.is_repeated:
                for index in range(len(value) - 1, -1, -1):
                    if getattr(value[index], mac_field, None) != target:
                        del value[index]
                matched = matched or bool(value)
            elif getattr(value, mac_field, None) == target:
                matched = True
            else:
                telemetry.ClearField(field_name)
        elif field_name not in {"meta", "reporter"}:
            telemetry.ClearField(field_name)
    return matched


def _credential_field(name: str) -> bool:
    name = name.lower().replace("_", "")
    return any(part in name for part in ("token", "password", "secret")) or name in {
        "bondingkey", "publickey", "privatekey", "key", "authorization", "apikey",
    }


def _collect_secrets(message: Message, secrets: set[str]) -> None:
    for descriptor, value in message.ListFields():
        if descriptor.type == FieldDescriptor.TYPE_MESSAGE:
            for child in value if descriptor.is_repeated else (value,):
                _collect_secrets(child, secrets)
        elif _credential_field(descriptor.name):
            for secret in value if descriptor.is_repeated else (value,):
                if isinstance(secret, str) and secret:
                    secrets.add(secret)


def _redact_text(value: str, secrets) -> str:
    for secret in sorted((secret for secret in secrets if secret), key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    return value


def _sanitize(message: Message, secrets: set[str]) -> None:
    for descriptor, value in list(message.ListFields()):
        if _credential_field(descriptor.name):
            message.ClearField(descriptor.name)
        elif descriptor.type == FieldDescriptor.TYPE_MESSAGE:
            for child in value if descriptor.is_repeated else (value,):
                _sanitize(child, secrets)
        elif descriptor.type in (FieldDescriptor.TYPE_STRING, FieldDescriptor.TYPE_BYTES):
            def redact(item):
                if isinstance(item, str):
                    return _redact_text(item, secrets)
                for secret in sorted(secrets, key=len, reverse=True):
                    item = item.replace(secret.encode("utf-8"), b"[REDACTED]")
                return item

            if descriptor.is_repeated:
                for index, item in enumerate(value):
                    value[index] = redact(item)
            else:
                setattr(message, descriptor.name, redact(value))
