from __future__ import annotations

from typing import Any

from .const import CONF_ACCESS_TOKEN, CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_AP_SOURCE


async def async_get_config_entry_diagnostics(hass, entry) -> dict[str, Any]:
    tokens = tuple(
        token
        for token in (
            entry.data.get(CONF_ACCESS_TOKEN), entry.options.get(CONF_ACCESS_TOKEN)
        )
        if isinstance(token, str) and token
    )
    redacted_data = _redact_credentials(entry.data, tokens)

    payload: dict[str, Any] = {
        "domain": DOMAIN,
        "entry": redacted_data,
        "options": _redact_credentials(entry.options, tokens),
    }
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_AP_SOURCE:
        payload["runtime"] = None
        return payload

    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        payload["runtime"] = None
        return payload

    runtime_payload = dict(runtime.diagnostic_attributes())
    runtime_payload["receiver_connected_sources"] = sorted(
        runtime_payload.get("receiver_connected_sources", [])
    )
    payload["runtime"] = _redact_credentials(runtime_payload, tokens)
    payload["packet_capture"] = runtime.export_packet_capture()
    return payload


def _redact_credentials(data, tokens: tuple[str, ...] = ()):
    if isinstance(data, dict):
        return {
            key: (
                "***redacted***"
                if str(key).replace("_", "").lower() in {"accesstoken", "token"}
                else _redact_credentials(value, tokens)
            )
            for key, value in data.items()
        }
    if isinstance(data, (list, tuple)):
        return [_redact_credentials(value, tokens) for value in data]
    if isinstance(data, str):
        for token in tokens:
            data = data.replace(token, "***redacted***")
    return data
