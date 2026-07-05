"""Constants for the MelcoBEMS MINI (A1M) integration.

Register map: MELCOBEMS MINI (A1M) Install & User Manual, Air-To-Air table
(holding registers 0-19 + coil 0). All temperatures are degC x10 unless noted.
"""
from __future__ import annotations

DOMAIN = "melcobems_a1m"

# --- connection defaults -----------------------------------------------------
CONF_CONNECTION = "connection"
CONF_SERIAL_PORT = "serial_port"
CONF_TCP_HOST = "tcp_host"
CONF_TCP_PORT = "tcp_port"
CONF_BAUDRATE = "baudrate"
CONF_SLAVES = "slaves"  # list[{"id": int, "name": str}]
CONN_SERIAL = "serial"
CONN_TCP = "tcp"
DEFAULT_BAUDRATE = 9600
DEFAULT_SCAN_INTERVAL = 30  # seconds

# --- options -----------------------------------------------------------------
OPT_SCAN_INTERVAL = "scan_interval"
OPT_EXT_ENTITY = "ext_entity_{slave}"      # external room temperature entity
OPT_OFFSET_ENABLED = "offset_enabled_{slave}"
EXT_STALE_SECONDS = 7200                    # source older than this -> feed 0 (disable)

# --- A1M Air-To-Air holding registers (0-based protocol addresses) ------------
REG_MODE = 0            # RW 1=heat 2=dry 3=cool 7=fan 8=auto(unsupported on 2-pipe PUMY)
REG_SETPOINT = 1        # RW degC x10
REG_FAN = 2             # RW 0=auto 2=low 3=med 5=high 6=very high
# 3 = vane (N/A on PEFY ducted), 4/5/6 = slave/baud/parity -> NEVER TOUCH
REG_POWER = 7           # RW 0=off 1=on
REG_RETURN_AIR = 8      # RO degC x10 (TH21 return air thermistor)
REG_FW = 10             # RO firmware, e.g. 30029 = 3.0.29
REG_COMMS = 11          # RO comms counter, wraps at 65535
REG_FAULT = 12          # RO 8000=OK, 6999=CN105 comms fault, else unit fault code
REG_SYSTYPE = 13        # RO 0 = Air-To-Air
REG_DEADBAND = 14       # RO mirrors DIP 8 (A1M auto-emulation)
REG_BMS_ROOM_SIGNED = 15    # RW same cell as 16, two's-complement
REG_BMS_ROOM = 16       # RW degC x10 unsigned; 0 disables Setpoint Offset; volatile
REG_VSP = 17            # RW virtual setpoint degC x10; EEPROM-backed - write on change only
REG_DB_HEAT = 18        # RW deadband heating setpoint degC x1 (NOT x10)
REG_DB_COOL = 19        # RW deadband cooling setpoint degC x1 (NOT x10)
BLOCK_START = 0
BLOCK_COUNT = 20

FAULT_OK = 8000
FAULT_CN105 = 6999

# BMS room temperature write clamp: a legitimate 0.0 C must never silently
# disable the feature; A1M treats 0 as "offset off".
BMS_MIN = 1
BMS_MAX = 500

# --- value maps ----------------------------------------------------------------
MODE_TO_HVAC = {1: "heat", 9: "heat", 2: "dry", 10: "dry", 3: "cool", 11: "cool", 7: "fan_only"}
HVAC_TO_MODE = {"heat": 1, "dry": 2, "cool": 3, "fan_only": 7}
FAN_TO_HA = {0: "auto", 2: "low", 3: "medium", 5: "high", 6: "top"}
HA_TO_FAN = {v: k for k, v in FAN_TO_HA.items()}

MIN_TEMP = 17.0
MAX_TEMP = 30.0
TEMP_STEP = 0.5

MANUFACTURER = "Mitsubishi Electric"
BUS_MODEL = "MelcoBEMS MINI (A1M) RS-485 bus"
UNIT_MODEL = "City Multi indoor unit (via A1M)"
