from custom_components.aruba_ble_proxy.const import (
    CONF_ACCESS_TOKEN,
    CONF_ENTRY_TYPE,
    CONF_LISTEN_HOST,
    CONF_LISTEN_PORT,
    CONF_PUBLIC_HOST,
    CONF_PUBLIC_SCHEME,
    CONF_TRANSPORT_PREFIX,
    ENTRY_TYPE_AP_SOURCE,
    ENTRY_TYPE_LISTENER,
)
from custom_components.aruba_ble_proxy.diagnostics import async_get_config_entry_diagnostics
import asyncio


class _FakeRuntime:
    def diagnostic_attributes(self):
        return {
            "receiver_connected_sources": ["aa:bb:cc:dd:ee:ff"],
            "receiver_crashed": False,
        }

    def export_packet_capture(self):
        return {
            "active": False,
            "packet_count": 1,
            "packets": [{"message": {"bleData": [{"mac": "qrvM3e7/"}]}}],
        }


class _FakeEntry:
    data = {
        CONF_ENTRY_TYPE: ENTRY_TYPE_LISTENER,
        CONF_LISTEN_HOST: "0.0.0.0",
        CONF_LISTEN_PORT: 7443,
        CONF_PUBLIC_HOST: "ha.example.local",
        CONF_PUBLIC_SCHEME: "ws",
        CONF_TRANSPORT_PREFIX: "ha-ble",
        CONF_ACCESS_TOKEN: "secret",
    }
    options = {}
    runtime_data = _FakeRuntime()


def test_diagnostics_redacts_access_token():
    async def run_test():
        result = await async_get_config_entry_diagnostics(None, _FakeEntry())

        assert result["entry"][CONF_ACCESS_TOKEN] == "***redacted***"
        assert result["runtime"]["receiver_connected_sources"] == ["aa:bb:cc:dd:ee:ff"]

    asyncio.run(run_test())


def test_diagnostics_redacts_access_token_from_options_too():
    class Entry(_FakeEntry):
        options = {CONF_ACCESS_TOKEN: "legacy-secret"}

    async def run_test():
        result = await async_get_config_entry_diagnostics(None, Entry())

        assert result["options"][CONF_ACCESS_TOKEN] == "***redacted***"

    asyncio.run(run_test())


def test_listener_diagnostics_contains_capture_download_with_json_safe_packets():
    import json

    async def run_test():
        result = await async_get_config_entry_diagnostics(None, _FakeEntry())

        assert result["packet_capture"]["packet_count"] == 1
        assert result["packet_capture"]["packets"][0]["message"]["bleData"]
        assert "secret" not in json.dumps(result)

    asyncio.run(run_test())


def test_ap_child_diagnostics_does_not_export_entire_listener_capture():
    class Entry(_FakeEntry):
        data = {CONF_ENTRY_TYPE: ENTRY_TYPE_AP_SOURCE}

    async def run_test():
        result = await async_get_config_entry_diagnostics(None, Entry())

        assert result["runtime"] is None
        assert "packet_capture" not in result

    asyncio.run(run_test())


def test_unloaded_listener_diagnostics_has_no_capture():
    class Entry(_FakeEntry):
        runtime_data = None

    async def run_test():
        result = await async_get_config_entry_diagnostics(None, Entry())

        assert result["runtime"] is None
        assert "packet_capture" not in result

    asyncio.run(run_test())


def test_diagnostics_redacts_literal_credentials_inside_runtime_messages_and_nested_options():
    class Runtime(_FakeRuntime):
        def diagnostic_attributes(self):
            return {
                "receiver_last_error": "Decode failed: secret / legacy-secret",
                "nested": [{"accessToken": "unexpected credential"}],
            }

    class Entry(_FakeEntry):
        runtime_data = Runtime()
        options = {CONF_ACCESS_TOKEN: "legacy-secret", "nested": {"token": "other"}}

    async def run_test():
        result = await async_get_config_entry_diagnostics(None, Entry())

        assert "secret" not in result["runtime"]["receiver_last_error"]
        assert result["runtime"]["nested"][0]["accessToken"] == "***redacted***"
        assert result["options"]["nested"]["token"] == "***redacted***"

    asyncio.run(run_test())
