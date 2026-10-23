import asyncio

import pytest

from custom_components.aruba_ble_proxy.runtime import ArubaBleProxyRuntime


def _runtime():
    return ArubaBleProxyRuntime(
        hass=None, host="0.0.0.0", port=7443, access_token="secret"
    )


def test_capture_runtime_delegates_settings_status_stop_and_export():
    async def run_test():
        runtime = _runtime()
        runtime._task = asyncio.create_task(asyncio.Event().wait())
        try:
            status = runtime.start_packet_capture(
                device_mac="aabbccddeeff", timeout=120, max_bytes=2048
            )
            assert status["active"] is True
            assert status["device_mac"] == "AA:BB:CC:DD:EE:FF"
            assert status["timeout"] == 120
            assert status["max_bytes"] == 2048
            assert runtime.packet_capture_status() == status
            assert "packets" not in runtime.packet_capture_status()
            stopped = runtime.stop_packet_capture()
            assert stopped["active"] is False
            assert stopped["stop_reason"] == "manual"
            assert runtime.export_packet_capture()["packets"] == []
        finally:
            await runtime.async_stop()

    asyncio.run(run_test())


def test_capture_runtime_rejects_start_when_receiver_is_unavailable():
    async def run_test():
        runtime = _runtime()
        with pytest.raises(ValueError, match="receiver is not running"):
            runtime.start_packet_capture()

        runtime._task = asyncio.create_task(asyncio.sleep(0))
        await runtime._task
        with pytest.raises(ValueError, match="receiver is not running"):
            runtime.start_packet_capture()

    asyncio.run(run_test())


def test_runtime_unload_clears_packets_and_cancels_capture_timeout():
    async def run_test():
        runtime = _runtime()
        runtime._task = asyncio.create_task(asyncio.Event().wait())
        runtime.start_packet_capture()
        runtime._receiver.capture.record_message(b"", peer="test", connection_id=1)
        assert runtime.packet_capture_status()["packet_count"] == 1
        timer = runtime._receiver.capture._timer

        await runtime.async_stop()

        assert runtime._task is None
        assert runtime.packet_capture_status()["active"] is False
        assert runtime.export_packet_capture()["packets"] == []
        assert timer.cancelled()

    asyncio.run(run_test())


@pytest.mark.parametrize("outcome", ["crash", "return", "cancel"])
def test_receiver_exit_stops_capture_and_preserves_download(outcome):
    async def run_test():
        runtime = _runtime()

        async def receiver():
            if outcome == "crash":
                raise RuntimeError("receiver failure")
            if outcome == "cancel":
                await asyncio.Event().wait()

        runtime._task = asyncio.create_task(receiver())
        runtime.start_packet_capture()
        runtime._receiver.capture.record_message(b"", peer="test", connection_id=1)
        if outcome == "cancel":
            runtime._task.cancel()
        try:
            await runtime._task
        except (RuntimeError, asyncio.CancelledError):
            pass
        runtime._handle_receiver_task_done(runtime._task)

        status = runtime.packet_capture_status()
        assert status["active"] is False
        assert status["stop_reason"] == "receiver_stopped"
        assert status["packet_count"] == 1
        assert len(runtime.export_packet_capture()["packets"]) == 1
        assert runtime.stats.receiver_crashed is (outcome != "cancel")

    asyncio.run(run_test())
