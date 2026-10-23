import asyncio
import base64
import json
import sys

import pytest

from custom_components.aruba_ble_proxy.aruba_proto import ArubaTelemetryDecoder
from custom_components.aruba_ble_proxy.aruba_iot_ble.packet_capture import PacketCapture


TOKEN = "capture-secret-token"
DEVICE = bytes.fromhex("112233445566")
OTHER_DEVICE = bytes.fromhex("aabbccddeeff")
PAYLOAD = bytes.fromhex("0201060303d2fc08094154435f313233")


@pytest.fixture
def telemetry_cls():
    return ArubaTelemetryDecoder()._pb.telemetry_cls


def empty_telemetry(telemetry_cls):
    message = telemetry_cls()
    message.meta.access_token = TOKEN
    message.meta.version = 1
    message.reporter.name = "ap-01"
    message.reporter.mac = bytes.fromhex("001122334455")
    message.reporter.ipv4 = "192.0.2.10"
    return message


def telemetry_message(telemetry_cls):
    message = empty_telemetry(telemetry_cls)
    for mac in (DEVICE, OTHER_DEVICE):
        message.bleData.add(mac=mac, data=PAYLOAD, rssi=-61)
        message.reported.add(mac=mac, localName="sensor")
        message.characteristics.add(deviceMac=mac, value=b"\x00\x01\xfe\xff")
        message.results.add(deviceMac=mac, actionId="read-123")
    message.status.deviceMac = OTHER_DEVICE
    message.status.statusString = "other device disconnected"
    message.wifiData.add(mac=OTHER_DEVICE, rssi=-45)
    message.devCount.dev_allBleData = 2
    message.apHealth.apStatus = 0
    return message


def record(capture, message, **kwargs):
    capture.record_message(
        message,
        peer="192.0.2.10:12345",
        connection_id=42,
        **kwargs,
    )


def test_listener_capture_preserves_payload_and_removes_credentials(telemetry_cls):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls, access_token=TOKEN)
        message = telemetry_message(telemetry_cls)
        message.reporter.name = f"ap-{TOKEN}"
        message.results[0].bondingKey.key = b"private-bonding-key"
        wire = message.SerializeToString()
        # A length-delimited unknown field must never be preserved as a raw frame.
        unknown_secret = b"unknown-field-secret"
        wire += b"\xfa\x7f" + bytes([len(unknown_secret)]) + unknown_secret
        capture.start()
        record(capture, wire)
        capture.stop()

        exported = capture.export()
        serialized = json.dumps(exported)
        assert exported["packet_count"] == 1
        packet = exported["packets"][0]
        assert packet["connection_id"] == 42
        assert packet["peer"] == "192.0.2.10:12345"
        assert packet["byte_length"] == len(wire)
        assert packet["timestamp"]
        assert packet["outcome"] == "received"
        telemetry = packet["telemetry"]
        assert len(telemetry["bleData"]) == 2
        assert base64.b64decode(telemetry["bleData"][0]["data"]) == PAYLOAD
        assert base64.b64decode(telemetry["characteristics"][0]["value"]) == b"\x00\x01\xfe\xff"
        assert "wifiData" in telemetry
        assert "apHealth" in telemetry
        assert "devCount" in telemetry
        assert "access_token" not in telemetry["meta"]
        assert "bondingKey" not in telemetry["results"][0]
        for secret in (
            TOKEN,
            base64.b64encode(TOKEN.encode()).decode(),
            "private-bonding-key",
            base64.b64encode(b"private-bonding-key").decode(),
            unknown_secret.decode(),
            base64.b64encode(wire).decode(),
        ):
            assert secret not in serialized

    asyncio.run(run_test())


def test_capture_scrubs_discovered_token_from_strings_and_byte_payloads(telemetry_cls):
    async def run_test():
        # Token validation may be disabled, so redact the token found in meta too.
        capture = PacketCapture(telemetry_cls=telemetry_cls)
        message = empty_telemetry(telemetry_cls)
        message.reporter.name = f"before-{TOKEN}-after"
        message.bleData.add(mac=DEVICE, data=b"prefix-" + TOKEN.encode() + b"-suffix")
        message.characteristics.add(deviceMac=DEVICE, value=TOKEN.encode())
        capture.start()
        record(capture, message.SerializeToString())
        capture.stop()
        exported = capture.export()
        telemetry = exported["packets"][0]["telemetry"]
        assert "access_token" not in telemetry.get("meta", {})
        assert TOKEN not in telemetry["reporter"]["name"]
        assert TOKEN.encode() not in base64.b64decode(telemetry["bleData"][0]["data"])
        assert TOKEN.encode() not in base64.b64decode(telemetry["characteristics"][0]["value"])
        assert TOKEN not in json.dumps(exported)

    asyncio.run(run_test())


@pytest.mark.parametrize("device_mac", ["11:22:33:44:55:66", "11-22-33-44-55-66", "112233445566"])
def test_device_capture_prunes_every_batch_section(telemetry_cls, device_mac):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls, access_token=TOKEN)
        capture.start(device_mac=device_mac)
        record(capture, telemetry_message(telemetry_cls).SerializeToString())
        capture.stop()
        exported = capture.export()
        assert exported["device_mac"] == "11:22:33:44:55:66"
        assert exported["packet_count"] == 1
        telemetry = exported["packets"][0]["telemetry"]
        for section, field in (
            ("bleData", "mac"),
            ("reported", "mac"),
            ("characteristics", "deviceMac"),
            ("results", "deviceMac"),
        ):
            assert len(telemetry[section]) == 1
            assert base64.b64decode(telemetry[section][0][field]) == DEVICE
        assert base64.b64decode(telemetry["bleData"][0]["data"]) == PAYLOAD
        assert "reporter" in telemetry
        assert "status" not in telemetry
        assert "wifiData" not in telemetry
        assert "devCount" not in telemetry
        assert "apHealth" not in telemetry

    asyncio.run(run_test())


def test_device_capture_matches_case_and_retains_device_status(telemetry_cls):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls)
        capture.start(device_mac="AA:BB:CC:DD:EE:FF")
        message = empty_telemetry(telemetry_cls)
        message.status.deviceMac = OTHER_DEVICE
        message.status.statusString = "disconnected"
        record(capture, message.SerializeToString())
        capture.stop()
        assert capture.status()["device_mac"] == "AA:BB:CC:DD:EE:FF"
        telemetry = capture.export()["packets"][0]["telemetry"]
        assert base64.b64decode(telemetry["status"]["deviceMac"]) == OTHER_DEVICE
        assert telemetry["status"]["statusString"] == "disconnected"

    asyncio.run(run_test())


def test_device_capture_omits_unrelated_packets_and_unsafe_messages(telemetry_cls):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls, access_token=TOKEN)
        capture.start(device_mac="11:22:33:44:55:66")
        unrelated = empty_telemetry(telemetry_cls)
        unrelated.bleData.add(mac=OTHER_DEVICE, data=PAYLOAD)
        record(capture, unrelated.SerializeToString())
        record(capture, f"malformed text {TOKEN}")
        record(capture, b"\xff" + TOKEN.encode())
        record(capture, telemetry_message(telemetry_cls).SerializeToString(), outcome="auth_error")
        capture.stop()
        assert capture.export()["packets"] == []
        assert capture.status()["packet_count"] == 0

    asyncio.run(run_test())


def test_listener_retains_only_metadata_for_unsafe_messages(telemetry_cls):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls, access_token=TOKEN)
        capture.start()
        record(capture, f"text includes {TOKEN}")
        record(capture, b"\xffunparseable-other-secret")
        record(capture, telemetry_message(telemetry_cls).SerializeToString(), outcome="auth_error")
        capture.stop()
        exported = capture.export()
        assert exported["packet_count"] == 3
        for packet in exported["packets"]:
            assert not packet.get("telemetry")
            assert packet["byte_length"] > 0
            assert packet["connection_id"] == 42
        serialized = json.dumps(exported)
        assert TOKEN not in serialized
        assert "unparseable-other-secret" not in serialized
        assert base64.b64encode(b"\xffunparseable-other-secret").decode() not in serialized

    asyncio.run(run_test())


def test_stop_preserves_download_and_ignores_future_packets(telemetry_cls):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls)
        wire = telemetry_message(telemetry_cls).SerializeToString()
        record(capture, wire)
        assert capture.export()["packets"] == []
        capture.start()
        record(capture, wire)
        stopped = capture.stop()
        before = capture.export()
        record(capture, wire)
        assert capture.export() == before
        assert not stopped["active"]
        assert stopped["stop_reason"] == "manual"
        assert stopped["stopped_at"]
        assert stopped["packet_count"] == 1
        assert capture.stop() == stopped

    asyncio.run(run_test())


def test_restarting_capture_requires_stop_then_replaces_previous_data(telemetry_cls):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls)
        capture.start()
        record(capture, telemetry_message(telemetry_cls).SerializeToString())
        with pytest.raises(ValueError):
            capture.start()
        assert capture.status()["packet_count"] == 1
        capture.stop()
        started = capture.start(device_mac="11:22:33:44:55:66")
        assert started["active"]
        assert started["packet_count"] == 0
        assert started["bytes_used"] == 0
        assert started["dropped_packets"] == 0
        assert started["stopped_at"] is None
        assert started["stop_reason"] is None
        assert capture.export()["packets"] == []
        capture.clear()

    asyncio.run(run_test())


def test_capture_memory_limit_stops_without_exceeding_budget(telemetry_cls):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls)
        capture.start(max_bytes=4096)
        wire = telemetry_message(telemetry_cls).SerializeToString()
        for _ in range(100):
            record(capture, wire)
            retained_bytes = sum(sys.getsizeof(packet) for packet in capture._packets)
            retained_bytes += sys.getsizeof(capture._packets) - sys.getsizeof([])
            assert retained_bytes <= capture.status()["bytes_used"] <= 4096
            if not capture.status()["active"]:
                break
        status = capture.status()
        assert not status["active"]
        assert status["stop_reason"] == "memory_limit"
        assert 0 < status["bytes_used"] <= 4096
        assert status["dropped_packets"] >= 1
        exported = capture.export()
        serialized_records_size = sum(
            len(json.dumps(packet, separators=(",", ":")).encode())
            for packet in exported["packets"]
        )
        assert serialized_records_size <= status["bytes_used"]
        before = capture.export()
        record(capture, wire)
        assert capture.export() == before

    asyncio.run(run_test())


def test_oversized_packet_is_not_retained(telemetry_cls):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls)
        capture.start(max_bytes=1024)
        message = empty_telemetry(telemetry_cls)
        message.bleData.add(mac=DEVICE, data=b"x" * 4096)
        record(capture, message.SerializeToString())
        status = capture.status()
        assert not status["active"]
        assert status["stop_reason"] == "memory_limit"
        assert status["bytes_used"] == 0
        assert status["packet_count"] == 0
        assert status["dropped_packets"] == 1
        assert capture.export()["packets"] == []

    asyncio.run(run_test())


def test_capture_timeout_stops_while_socket_is_idle(telemetry_cls):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls)
        capture.start(timeout=1)
        record(capture, telemetry_message(telemetry_cls).SerializeToString())
        await asyncio.sleep(1.05)
        status = capture.status()
        assert not status["active"]
        assert status["stop_reason"] == "timeout"
        assert status["stopped_at"]
        assert status["packet_count"] == 1
        assert len(capture.export()["packets"]) == 1

    asyncio.run(run_test())


def test_clear_releases_capture_and_cancels_previous_timeout(telemetry_cls):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls)
        capture.start(timeout=1)
        record(capture, telemetry_message(telemetry_cls).SerializeToString())
        capture.clear()
        assert not capture.status()["active"]
        assert capture.status()["bytes_used"] == 0
        assert capture.export()["packets"] == []
        capture.start(timeout=60)
        await asyncio.sleep(1.05)
        assert capture.status()["active"]
        capture.clear()

    asyncio.run(run_test())


@pytest.mark.parametrize(
    "options",
    [
        {"device_mac": "not-a-mac"},
        {"device_mac": "11:22:33:44:55"},
        {"timeout": 0},
        {"timeout": -1},
        {"timeout": 301},
        {"timeout": True},
        {"timeout": 1.5},
        {"max_bytes": 0},
        {"max_bytes": -1},
        {"max_bytes": 1023},
        {"max_bytes": 10485761},
        {"max_bytes": True},
    ],
)
def test_invalid_capture_options_are_rejected(telemetry_cls, options):
    async def run_test():
        capture = PacketCapture(telemetry_cls=telemetry_cls)
        with pytest.raises(ValueError):
            capture.start(**options)
        assert not capture.status()["active"]

    asyncio.run(run_test())
