from __future__ import annotations

DOMAIN = "aruba_ble_proxy"

CONF_LISTEN_HOST = "listen_host"
CONF_LISTEN_PORT = "listen_port"
CONF_PUBLIC_HOST = "public_host"
CONF_PUBLIC_SCHEME = "public_scheme"
CONF_ENDPOINT_PATH = "endpoint_path"
CONF_ACCESS_TOKEN = "access_token"
CONF_TRANSPORT_PREFIX = "transport_prefix"
CONF_RADIO_PROFILE = "radio_profile"
CONF_ENABLE_RADIO_PROFILE = "enable_radio_profile"
CONF_ENABLE_ACTIVE_BLE = "enable_active_ble"
CONF_ACTIVE_CONNECTION_SLOTS = "active_connection_slots"
CONF_SETUP_COMPLETE = "setup_complete"
CONF_ENTRY_TYPE = "entry_type"
CONF_PARENT_ENTRY_ID = "parent_entry_id"
CONF_AP_SOURCE = "ap_source"
CONF_AP_MODEL = "ap_model"

ENTRY_TYPE_LISTENER = "listener"
ENTRY_TYPE_AP_SOURCE = "ap_source"

DEFAULT_LISTEN_HOST = "0.0.0.0"
DEFAULT_LISTEN_PORT = 7443
DEFAULT_PUBLIC_SCHEME = "ws"
DEFAULT_ENDPOINT_PATH = "/aruba-ble-proxy"
DEFAULT_TRANSPORT_PREFIX = "ha-ble"
DEFAULT_RADIO_PROFILE = "ha-ble-radio"
DEFAULT_ENABLE_ACTIVE_BLE = True
DEFAULT_ACTIVE_CONNECTION_SLOTS = 3
DEFAULT_AP_MODEL = "Aruba AP"
DEFAULT_CAPTURE_TIMEOUT = 60
MAX_CAPTURE_TIMEOUT = 300
DEFAULT_CAPTURE_MAX_BYTES = 1024 * 1024
MIN_CAPTURE_MAX_BYTES = 1024
MAX_CAPTURE_MAX_BYTES = 10 * 1024 * 1024

SERVICE_GENERATE_CLI = "generate_cli"
SERVICE_GENERATE_CLEANUP_CLI = "generate_cleanup_cli"
SERVICE_BLE_CONNECT = "ble_connect"
SERVICE_BLE_DISCONNECT = "ble_disconnect"
SERVICE_GATT_READ = "gatt_read"
SERVICE_GATT_WRITE = "gatt_write"
SERVICE_GATT_NOTIFY = "gatt_notify"
SERVICE_START_CAPTURE = "start_capture"
SERVICE_STOP_CAPTURE = "stop_capture"
