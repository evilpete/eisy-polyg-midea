"""
Conversions between msmart's device model and ISY driver/command values.

msmart works exclusively in Celsius, so all temperature values crossing this
boundary get converted according to the configured display units.
"""

from typing import Optional

# ISY unit-of-measure codes used by the profile.
UOM_BOOL = 2
UOM_CELSIUS = 4
UOM_FAHRENHEIT = 17
UOM_HUMIDITY = 22
UOM_INDEX = 25
UOM_KWH = 33
UOM_PERCENT = 51
UOM_RAW = 56
UOM_WATT = 73
UOM_HZ = 90

# GV0 / M_CONN index values.
CONN_OFFLINE = 0
CONN_ONLINE = 1
CONN_AUTH_FAILED = 2
CONN_UNSUPPORTED = 3
CONN_CONNECTING = 4

# Controller ST / M_CTLST index values.
CTRL_NOT_CONNECTED = 0
CTRL_CONNECTED = 1
CTRL_ERROR = 2


def c_to_f(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0


def f_to_c(fahrenheit: float) -> float:
    return (fahrenheit - 32.0) * 5.0 / 9.0


def temp_to_isy(celsius: Optional[float], fahrenheit: bool) -> Optional[float]:
    """Convert a Celsius reading from the device into the display unit."""
    if celsius is None:
        return None
    value = c_to_f(celsius) if fahrenheit else celsius
    return round(value, 1)


def temp_from_isy(value: float, fahrenheit: bool) -> float:
    """Convert a setpoint coming from the ISY back into Celsius."""
    return f_to_c(value) if fahrenheit else value


def bool_to_isy(value: Optional[bool]) -> Optional[int]:
    if value is None:
        return None
    return 1 if value else 0


def parse_bool(value, default: bool = False) -> bool:
    """Accept the many shapes a boolean takes in PG3 custom params."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ('1', 'true', 'yes', 'on', 'y', 't', 'enable', 'enabled'):
        return True
    if text in ('0', 'false', 'no', 'off', 'n', 'f', 'disable', 'disabled'):
        return False
    return default


def parse_int(value, default: Optional[int] = None) -> Optional[int]:
    text = str(value).strip() if value is not None else ''
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        pass
    try:
        # Allow 0x... for a device id copied out of a hex dump.
        return int(text, 0)
    except (TypeError, ValueError):
        return default


def command_value(command, fallback=None):
    """Pull the parameter out of an ISY command payload."""
    if not isinstance(command, dict):
        return fallback
    value = command.get('value')
    if value is None:
        query = command.get('query') or {}
        if query:
            value = next(iter(query.values()))
    return fallback if value is None else value


def address_for(device_id: int) -> str:
    """Build a legal ISY node address (<=14 chars) from a Midea device id.

    Midea ids are 6 bytes, so the hex form is at most 12 characters.
    """
    return 'ac{:012x}'.format(int(device_id) & 0xFFFFFFFFFFFF)


def safe_name(name: str) -> str:
    """ISY node names reject a handful of punctuation characters."""
    cleaned = ''.join(
        ch if (ch.isalnum() or ch in ' _-.') else ' ' for ch in str(name))
    cleaned = ' '.join(cleaned.split())
    return cleaned[:30] or 'Midea AC'
