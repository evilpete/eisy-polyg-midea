# Change log

## 1.0.0

Initial release.

* Local LAN monitoring and control of Midea air conditioners (device type
  `0xAC`) via the msmart-ng library. The Midea cloud is never contacted at
  runtime.
* Broadcast discovery plus per-device overrides in Custom Parameters.
* V3 devices authenticate from a token and key held in Custom Parameters.
* Per-device capability query: unsupported features are neither reported as
  readings nor sent as commands.
* Power, mode, fan speed (preset and percentage), target temperature, indoor
  and outdoor temperature, swing and louver angles, eco, turbo, sleep, freeze
  protection, display, purifier, follow me, filter alert, self clean, breeze
  mode, fresh air, power gear, aux heat, humidity, error code, and optional
  energy and extended sensor readings.
* Temperatures in Fahrenheit or Celsius.
