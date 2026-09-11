"""
ISY node for a Midea air conditioner (device type 0xAC).
"""

import udi_interface

from msmart.device import AirConditioner as AC
from msmart.lan import AuthenticationError, ProtocolError

from .aioloop import RUNNER
from .mapping import (CONN_AUTH_FAILED, CONN_CONNECTING, CONN_OFFLINE,
                      CONN_ONLINE, CONN_UNSUPPORTED, UOM_BOOL, UOM_CELSIUS,
                      UOM_FAHRENHEIT, UOM_HUMIDITY, UOM_HZ, UOM_INDEX, UOM_KWH,
                      UOM_PERCENT, UOM_RAW, UOM_WATT, bool_to_isy,
                      command_value, parse_bool, temp_from_isy, temp_to_isy)

LOGGER = udi_interface.LOGGER

# Fan speed presets present in the M_FAN editor. Anything else is a custom
# percentage and is reported on GV2 instead.
FAN_PRESETS = (20, 40, 60, 80, 100, 102)


class MideaACNode(udi_interface.Node):
    """One Midea indoor unit."""

    id = 'MIDEAAC'

    drivers = [
        {'driver': 'ST', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV0', 'value': CONN_CONNECTING, 'uom': UOM_INDEX},
        {'driver': 'CLITEMP', 'value': 0, 'uom': UOM_FAHRENHEIT},
        {'driver': 'GV1', 'value': 0, 'uom': UOM_FAHRENHEIT},
        {'driver': 'CLISPC', 'value': 0, 'uom': UOM_FAHRENHEIT},
        {'driver': 'CLIMD', 'value': 1, 'uom': UOM_INDEX},
        {'driver': 'CLIFS', 'value': 102, 'uom': UOM_INDEX},
        {'driver': 'GV2', 'value': 0, 'uom': UOM_PERCENT},
        {'driver': 'CLIHUM', 'value': 0, 'uom': UOM_HUMIDITY},
        {'driver': 'GV3', 'value': 0, 'uom': UOM_HUMIDITY},
        {'driver': 'GV4', 'value': 0, 'uom': UOM_INDEX},
        {'driver': 'GV5', 'value': 0, 'uom': UOM_INDEX},
        {'driver': 'GV6', 'value': 0, 'uom': UOM_INDEX},
        {'driver': 'GV7', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV8', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV9', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV10', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV11', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV12', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV13', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV14', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV15', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV16', 'value': 0, 'uom': UOM_RAW},
        {'driver': 'GV17', 'value': 1, 'uom': UOM_INDEX},
        {'driver': 'GV18', 'value': 0, 'uom': UOM_INDEX},
        {'driver': 'GV19', 'value': 100, 'uom': UOM_INDEX},
        {'driver': 'GV20', 'value': 0, 'uom': UOM_INDEX},
        {'driver': 'GV21', 'value': 0, 'uom': UOM_KWH},
        {'driver': 'GV22', 'value': 0, 'uom': UOM_WATT},
        {'driver': 'GV23', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV24', 'value': 0, 'uom': UOM_BOOL},
        {'driver': 'GV25', 'value': 0, 'uom': UOM_HZ},
        {'driver': 'GV26', 'value': 0, 'uom': UOM_FAHRENHEIT},
        {'driver': 'GV27', 'value': 0, 'uom': UOM_FAHRENHEIT},
    ]

    def __init__(self, polyglot, primary, address, name, config, controller):
        super().__init__(polyglot, primary, address, name)

        self.poly = polyglot
        self.controller = controller
        self.config = dict(config)

        self.device = None
        self.capabilities_read = False
        self.connection_state = CONN_CONNECTING

        self._lock = RUNNER.new_lock()

        polyglot.subscribe(polyglot.START, self.start, address)

    # ------------------------------------------------------------------ setup

    def start(self):
        LOGGER.info('Starting node %s (%s)', self.name, self.address)
        self.setDriver('GV0', CONN_CONNECTING, force=True)
        self.setDriver('GV23', 1 if self.beep else 0, force=True)
        self.connect()

    @property
    def fahrenheit(self) -> bool:
        return self.controller.fahrenheit

    @property
    def beep(self) -> bool:
        return parse_bool(self.config.get('beep'), self.controller.beep)

    @property
    def temp_uom(self) -> int:
        return UOM_FAHRENHEIT if self.fahrenheit else UOM_CELSIUS

    def update_config(self, config: dict) -> None:
        """Accept a changed device definition from custom params."""
        changed = (
            config.get('ip') != self.config.get('ip')
            or config.get('port') != self.config.get('port')
            or config.get('token') != self.config.get('token')
            or config.get('key') != self.config.get('key')
        )
        self.config.update(config)
        if changed:
            LOGGER.info('Connection details changed for %s, reconnecting',
                        self.name)
            self.device = None
            self.capabilities_read = False
            self.connect()

    # ------------------------------------------------------------- connection

    def connect(self) -> bool:
        """Build, authenticate and interrogate the device."""
        try:
            RUNNER.run(self._connect())
            return True
        except AuthenticationError as ex:
            LOGGER.error('Authentication failed for %s: %s', self.name, ex)
            self._set_connection(CONN_AUTH_FAILED)
        except ValueError as ex:
            LOGGER.error('%s has an unusable token or key: %s', self.name, ex)
            self._set_connection(CONN_AUTH_FAILED)
        except (ProtocolError, TimeoutError, OSError) as ex:
            LOGGER.error('Could not reach %s at %s: %s',
                         self.name, self.config.get('ip'), ex)
            self._set_connection(CONN_OFFLINE)
        except Exception:
            LOGGER.exception('Unexpected error connecting to %s', self.name)
            self._set_connection(CONN_OFFLINE)
        return False

    async def _connect(self) -> None:
        async with self._lock:
            device = self.device

            if device is None:
                device = AC(ip=self.config['ip'],
                            port=int(self.config.get('port') or 6444),
                            device_id=int(self.config['id']))

                token = self.config.get('token')
                key = self.config.get('key')
                version = self.config.get('version')

                if token and key:
                    LOGGER.debug('Authenticating %s with stored token/key',
                                 self.name)
                    await device.authenticate(token, key)
                elif version == 3:
                    raise AuthenticationError(
                        'V3 device requires a token and key; add them to the '
                        'device entry in Custom Parameters')

                self.device = device

            if not self.capabilities_read:
                await device.get_capabilities()
                self.capabilities_read = True
                LOGGER.info('Capabilities for %s: %s', self.name,
                            device.serialize_capabilities())

            device.enable_energy_usage_requests = self.controller.energy_stats
            if self.controller.extended_sensors:
                device.enable_group1_data_requests = True
                device.enable_group5_data_requests = True
                device.enable_group7_data_requests = True
                device.enable_group11_data_requests = True

            await device.refresh()

        self.publish()

    # ------------------------------------------------------------------ polls

    def update(self) -> bool:
        """Refresh device state. Reconnects if we never got a connection."""
        if self.device is None or not self.capabilities_read:
            return self.connect()

        try:
            RUNNER.run(self._refresh())
            return True
        except AuthenticationError as ex:
            LOGGER.error('Authentication lost for %s: %s', self.name, ex)
            self.device = None
            self._set_connection(CONN_AUTH_FAILED)
        except (ProtocolError, TimeoutError, OSError) as ex:
            LOGGER.warning('Refresh failed for %s: %s', self.name, ex)
            self._set_connection(CONN_OFFLINE)
        except Exception:
            LOGGER.exception('Unexpected error refreshing %s', self.name)
            self._set_connection(CONN_OFFLINE)
        return False

    async def _refresh(self) -> None:
        async with self._lock:
            await self.device.refresh()
        self.publish()

    def query(self, command=None):
        self.update()
        self.reportDrivers()

    # ------------------------------------------------------------- publishing

    def _set_connection(self, state: int) -> None:
        self.connection_state = state
        self.setDriver('GV0', state)
        if state != CONN_ONLINE:
            # Leave the last known values in place, but stop claiming the unit
            # is powered on when we cannot talk to it.
            self.setDriver('ST', 0)

    def _set_temp(self, driver: str, celsius) -> None:
        value = temp_to_isy(celsius, self.fahrenheit)
        if value is not None:
            self.setDriver(driver, value, uom=self.temp_uom)

    def _set_opt(self, driver: str, value) -> None:
        if value is not None:
            self.setDriver(driver, value)

    def publish(self) -> None:
        """Push the device's current state out to the ISY."""
        device = self.device
        if device is None:
            return

        if not device.online:
            self._set_connection(CONN_OFFLINE)
            return
        if not device.supported:
            self._set_connection(CONN_UNSUPPORTED)
            return

        self._set_connection(CONN_ONLINE)

        self._set_opt('ST', bool_to_isy(device.power_state))
        self._set_temp('CLITEMP', device.indoor_temperature)
        self._set_temp('GV1', device.outdoor_temperature)
        self._set_temp('CLISPC', device.target_temperature)

        if device.operational_mode is not None:
            self.setDriver('CLIMD', int(device.operational_mode))

        fan = device.fan_speed
        if fan is not None:
            fan = int(fan)
            self.setDriver('GV2', min(max(fan, 0), 100))
            if fan in FAN_PRESETS:
                self.setDriver('CLIFS', fan)

        if device.supports_humidity:
            self._set_opt('CLIHUM', device.indoor_humidity)
        if device.supports_target_humidity:
            self._set_opt('GV3', device.target_humidity)

        if device.swing_mode is not None:
            self.setDriver('GV4', int(device.swing_mode))
        if device.supports_vertical_swing_angle:
            self.setDriver('GV5', int(device.vertical_swing_angle))
        if device.supports_horizontal_swing_angle:
            self.setDriver('GV6', int(device.horizontal_swing_angle))

        self._set_opt('GV7', bool_to_isy(device.eco))
        self._set_opt('GV8', bool_to_isy(device.turbo))
        self._set_opt('GV9', bool_to_isy(device.sleep))
        self._set_opt('GV10', bool_to_isy(device.freeze_protection))
        self._set_opt('GV11', bool_to_isy(device.display_on))
        self._set_opt('GV12', bool_to_isy(device.purifier))
        self._set_opt('GV13', bool_to_isy(device.follow_me))
        self._set_opt('GV14', bool_to_isy(device.filter_alert))
        self._set_opt('GV15', bool_to_isy(device.self_clean_active))
        self._set_opt('GV16', device.error_code)

        if device.supports_breeze_away or device.supports_breezeless:
            if device.breezeless:
                self.setDriver('GV17', 4)
            elif device.breeze_mild:
                self.setDriver('GV17', 3)
            elif device.breeze_away:
                self.setDriver('GV17', 2)
            else:
                self.setDriver('GV17', 1)

        if device.supports_fresh_air:
            self.setDriver('GV18', int(device.fresh_air_fan_speed))

        if device.rate_select is not None:
            self.setDriver('GV19', int(device.rate_select))
        if device.aux_mode is not None:
            self.setDriver('GV20', int(device.aux_mode))

        self._set_opt('GV21', device.get_total_energy_usage())
        self._set_opt('GV22', device.get_real_time_power_usage())

        self.setDriver('GV23', 1 if self.beep else 0)

        self._set_opt('GV24', bool_to_isy(device.defrost_active))
        self._set_opt('GV25', device.compressor_frequency)
        self._set_temp('GV26', device.indoor_coil_temperature)
        self._set_temp('GV27', device.outdoor_coil_temperature)

    # -------------------------------------------------------------- commands

    def _apply(self, **changes) -> bool:
        """Set properties on the device and push them out."""
        if self.device is None:
            LOGGER.warning('%s is not connected; ignoring command', self.name)
            return False

        try:
            RUNNER.run(self._apply_async(changes))
            return True
        except AuthenticationError as ex:
            LOGGER.error('Authentication lost for %s: %s', self.name, ex)
            self.device = None
            self._set_connection(CONN_AUTH_FAILED)
        except (ProtocolError, TimeoutError, OSError) as ex:
            LOGGER.error('Command to %s failed: %s', self.name, ex)
            self._set_connection(CONN_OFFLINE)
        except Exception:
            LOGGER.exception('Unexpected error commanding %s', self.name)
        return False

    async def _apply_async(self, changes: dict) -> None:
        async with self._lock:
            device = self.device
            device.beep = self.beep
            for attribute, value in changes.items():
                setattr(device, attribute, value)
            await device.apply()
        self.publish()

    # Power ---------------------------------------------------------------

    def cmd_don(self, command=None):
        self._apply(power_state=True)

    def cmd_dof(self, command=None):
        self._apply(power_state=False)

    # Climate -------------------------------------------------------------

    def cmd_set_temperature(self, command):
        value = command_value(command)
        if value is None:
            return

        try:
            value = float(value)
        except (TypeError, ValueError):
            LOGGER.error('Bad setpoint value %r', value)
            return

        # Some ISY firmware sends values scaled by the editor precision. A
        # setpoint an order of magnitude above the legal maximum is that, not a
        # real request.
        limit = 86.0 if self.fahrenheit else 30.0
        if value > limit * 2:
            value = value / 10.0

        celsius = temp_from_isy(value, self.fahrenheit)
        celsius = min(max(celsius, self.device.min_target_temperature),
                      self.device.max_target_temperature)
        self._apply(target_temperature=round(celsius * 2) / 2)

    def cmd_set_mode(self, command):
        value = command_value(command)
        if value is None:
            return
        self._apply(operational_mode=AC.OperationalMode(int(value)))

    def cmd_set_fan(self, command):
        value = command_value(command)
        if value is None:
            return
        self._apply(fan_speed=AC.FanSpeed(int(value)))

    def cmd_set_fan_percent(self, command):
        value = command_value(command)
        if value is None:
            return
        if not self.device or not self.device.supports_custom_fan_speed:
            LOGGER.warning('%s does not support custom fan speeds', self.name)
            return
        self._apply(fan_speed=min(max(int(value), 1), 100))

    def cmd_set_target_humidity(self, command):
        value = command_value(command)
        if value is None:
            return
        self._apply(target_humidity=min(max(int(value), 35), 85))

    # Airflow -------------------------------------------------------------

    def cmd_set_swing(self, command):
        value = command_value(command)
        if value is None:
            return
        self._apply(swing_mode=AC.SwingMode(int(value)))

    def cmd_set_vertical_angle(self, command):
        value = command_value(command)
        if value is None:
            return
        self._apply(vertical_swing_angle=AC.SwingAngle(int(value)))

    def cmd_set_horizontal_angle(self, command):
        value = command_value(command)
        if value is None:
            return
        self._apply(horizontal_swing_angle=AC.SwingAngle(int(value)))

    def cmd_set_fresh_air(self, command):
        value = command_value(command)
        if value is None:
            return
        self._apply(fresh_air_fan_speed=AC.FreshAirFanSpeed(int(value)))

    def cmd_set_breeze(self, command):
        value = command_value(command)
        if value is None:
            return

        mode = int(value)
        # The library exposes breeze as three mutually exclusive booleans;
        # setting one to False returns the unit to OFF.
        if mode == 2:
            self._apply(breeze_away=True)
        elif mode == 3:
            self._apply(breeze_mild=True)
        elif mode == 4:
            self._apply(breezeless=True)
        else:
            self._apply(breeze_away=False)

    # Presets / toggles ---------------------------------------------------

    def _cmd_bool(self, attribute, command):
        value = command_value(command)
        if value is None:
            return
        self._apply(**{attribute: parse_bool(value)})

    def cmd_set_eco(self, command):
        self._cmd_bool('eco', command)

    def cmd_set_turbo(self, command):
        self._cmd_bool('turbo', command)

    def cmd_set_sleep(self, command):
        self._cmd_bool('sleep', command)

    def cmd_set_freeze(self, command):
        self._cmd_bool('freeze_protection', command)

    def cmd_set_purifier(self, command):
        self._cmd_bool('purifier', command)

    def cmd_set_follow_me(self, command):
        self._cmd_bool('follow_me', command)

    def cmd_set_rate(self, command):
        value = command_value(command)
        if value is None:
            return
        self._apply(rate_select=AC.RateSelect(int(value)))

    def cmd_set_aux(self, command):
        value = command_value(command)
        if value is None:
            return
        self._apply(aux_mode=AC.AuxHeatMode(int(value)))

    # Display / misc ------------------------------------------------------

    def cmd_set_display(self, command):
        """The display is a toggle on the wire, so only act on a real change."""
        value = command_value(command)
        if value is None or self.device is None:
            return

        wanted = parse_bool(value)
        if self.device.display_on == wanted:
            self.setDriver('GV11', 1 if wanted else 0)
            return

        try:
            RUNNER.run(self._toggle_display())
        except Exception as ex:
            LOGGER.error('Display toggle failed for %s: %s', self.name, ex)

    async def _toggle_display(self) -> None:
        async with self._lock:
            await self.device.toggle_display()
        self.publish()

    def cmd_self_clean(self, command=None):
        if self.device is None:
            return
        if not self.device.supports_self_clean:
            LOGGER.warning('%s does not support self clean', self.name)
            return
        try:
            RUNNER.run(self._self_clean())
        except Exception as ex:
            LOGGER.error('Self clean failed for %s: %s', self.name, ex)

    async def _self_clean(self) -> None:
        async with self._lock:
            await self.device.start_self_clean()
            await self.device.refresh()
        self.publish()

    def cmd_set_beep(self, command):
        """Whether subsequent commands make the unit beep. Node server side."""
        value = command_value(command)
        if value is None:
            return
        self.config['beep'] = parse_bool(value)
        self.setDriver('GV23', 1 if self.config['beep'] else 0)

    commands = {
        'DON': cmd_don,
        'DOF': cmd_dof,
        'QUERY': query,
        'CLISPC': cmd_set_temperature,
        'CLIMD': cmd_set_mode,
        'CLIFS': cmd_set_fan,
        'SETFANPCT': cmd_set_fan_percent,
        'SETTHUM': cmd_set_target_humidity,
        'SETSWING': cmd_set_swing,
        'SETVANGLE': cmd_set_vertical_angle,
        'SETHANGLE': cmd_set_horizontal_angle,
        'SETECO': cmd_set_eco,
        'SETTURBO': cmd_set_turbo,
        'SETSLEEP': cmd_set_sleep,
        'SETFREEZE': cmd_set_freeze,
        'SETDISPLAY': cmd_set_display,
        'SETPURIFY': cmd_set_purifier,
        'SETFOLLOW': cmd_set_follow_me,
        'SETBREEZE': cmd_set_breeze,
        'SETFRESH': cmd_set_fresh_air,
        'SETRATE': cmd_set_rate,
        'SETAUX': cmd_set_aux,
        'SETBEEP': cmd_set_beep,
        'SELFCLEAN': cmd_self_clean,
    }
