# Schlage protocol reference

Developer notes on the protocols `pyschlage` speaks, derived by reverse
engineering the **Schlage Home Android app, version 8.2.0**
(`com.allegion.leopard`, decompiled with `jadx`). This is a reference for
contributors; it is not part of the published API documentation.

Everything below was read out of the app itself. Where the app and
`pyschlage` disagree, the app is treated as authoritative and the
difference is called out as a gap.

Internally Allegion calls the app "Leopard" and gives each lock platform a
code name (Denali = Encode, Jackalope = Encode Plus, Walton = Sense Pro,
WKD = Arrive, Selene = Gainsborough/Schlage Selene).

## Contents

- [Cloud service](#cloud-service)
  - [Endpoints](#endpoints)
  - [Device type IDs](#device-type-ids)
  - [Model capabilities](#model-capabilities)
  - [Device attributes](#device-attributes)
  - [Enumerations](#enumerations)
  - [Remote commands](#remote-commands)
  - [Access codes](#access-codes)
  - [Credentials (key fobs)](#credentials-key-fobs)
  - [Logs](#logs)
  - [Notifications](#notifications)
  - [Auto-lock times](#auto-lock-times)
  - [Push updates](#push-updates)
- [Bluetooth LE](#bluetooth-le)
  - [GATT profile](#gatt-profile)
  - [Packet framing](#packet-framing)
  - [Session establishment](#session-establishment)
  - [Record encryption](#record-encryption)
  - [RPC envelope](#rpc-envelope)
  - [Traits and attribute IDs](#traits-and-attribute-ids)
  - [Operation sequences](#operation-sequences)

## Cloud service

### Endpoints

The app ships an unencrypted JSON config blob in `classes*.dex` naming four
services:

| Name | Base URL | Purpose |
| --- | --- | --- |
| `thinCloud` | `https://api.allegion.yonomi.cloud/v1/` | The main device API. This is what `pyschlage.auth.BASE_URL` points at. |
| `catStar` | `https://catstar.allegion.yonomi.cloud/v1/` | Mints a per-session Cloud Access Token for BLE connections. |
| `payloadService` | `https://factory.allegion.yonomi.cloud/v1/` | "Payload 0" factory provisioning data, used during commissioning. |
| `firmwareService` | `https://api.allegionengage.com/api/` (version `3`) | Firmware manifests. |

Authentication is AWS Cognito SRP against user pool `us-west-2_2zhrVs9d4`
in `us-west-2`, exactly as `pyschlage.auth` implements it. Requests carry
the Cognito access token as `Authorization: Bearer ...` plus a static
`X-Api-Key`. The two `wss` endpoints additionally require
`X-Web-Identity-Token: <Cognito ID token>` — see
[Push updates](#push-updates).

`pyschlage` only talks to `thinCloud`. The other three are unused.

Paths seen in the app's Retrofit interfaces (`{...}` are path params; all
are sent URL-encoded):

```
GET    devices?archetype=lock
GET    devices?devicetypeId=br400
POST   devices
GET    devices/{deviceId}
PUT    devices/{deviceId}
DELETE devices/{deviceId}
POST   devices/{deviceId}/commands
POST   devices/{deviceId}/commands?async=true
POST   devices/{deviceId}/commands/{commandId}
GET    devices/{deviceId}/logs
DELETE devices/{deviceId}/logs
GET    devices/{deviceId}/storage/accesscode/
GET    devices/{deviceId}/storage/accesscode/{accessCodeId}
POST   devices/{deviceId}/storage/accesscode
PUT    devices/{deviceId}/storage/accesscode/{accessCodeId}
DELETE devices/{deviceId}/storage/accesscode/
DELETE devices/{deviceId}/storage/accesscode/{accessCodeId}
GET    devices/{deviceId}/storage/fob/
PUT    devices/{deviceId}/users/{userId}
DELETE devices/{deviceId}/users/{userId}
GET    users
GET    users/@me
GET    users/{userId}
GET    notifications
POST   notifications?deviceId={deviceId}
PUT    notifications/{notificationId}
DELETE notifications/{notificationId}
GET    wss?deviceId={deviceId}
GET    users/wss
GET    invitations
GET    invitations/{deviceId}
DELETE invitations/{inviteId}
POST   catstar/{deviceId}            (catStar base URL)
GET    devices?deviceType=&physicalId=   (payloadService base URL)
```

Notes on paths `pyschlage` does not use:

- The access-code **storage** endpoints are a full REST CRUD surface.
  `pyschlage` writes access codes exclusively through the
  `devices/{id}/commands` route (`addaccesscode` / `updateaccesscode` /
  `deleteaccesscode`), which is what the app does for WiFi locks. The
  storage `GET` is the one storage verb `pyschlage` does use.
- `?async=true` returns an `AsyncRemoteCommandResponse` carrying an `id`;
  the command's progress is then polled with
  `POST devices/{id}/commands/{commandId}`. `pyschlage` only issues
  synchronous commands.
- `GET wss` / `GET users/wss` return `{clientId, wssUri, topics[], message}`
  for the MQTT-over-WebSocket push channel. See
  [Push updates](#push-updates).

### Device type IDs

`devicetypeId` is a model prefix plus a transport suffix. The app matches
with `contains()`, so suffixed IDs must be handled.

| Prefix | Product | Platform code name | `pyschlage.device.DeviceType` |
| --- | --- | --- | --- |
| `br400` | Wi-Fi Adapter (BR400) | — | `BRIDGE` |
| `be459` | Schlage Arrive (BE459) | WKD, "Wifi Keypad Deadbolt" | `ARRIVE` |
| `be479` | Schlage Sense (BE479) | — | `SENSE` |
| `be489` | Schlage Encode (BE489) | Denali | `ENCODE` |
| `be499` | Schlage Encode Plus (BE499) | Jackalope | `ENCODE_PLUS` |
| `be889` | Schlage Sense Pro (BE889) | Walton | `SENSE_PRO` |
| `fe789` | Schlage Encode Lever (FE789) | — | `ENCODE_LEVER` |
| `gselent` | Gainsborough Selene Entrance (GSELENT) | Selene | `GAINSBOROUGH_SELENE_ENTRANCE` |
| `gselsec` | Gainsborough Selene Secure (GSELSEC) | Selene | `GAINSBOROUGH_SELENE_SECURE` |
| `sselent` | Schlage Selene Entrance (SSELENT) | Selene | `SCHLAGE_SELENE_ENTRANCE` |
| `sselsec` | Schlage Selene Secure (SSELSEC) | Selene | `SCHLAGE_SELENE_SECURE` |

Product names and model numbers are the app's own, from the
`all_product_list_items` array. `be479` and `br400` are not in that list —
Sense and the adapter are no longer offered for new installs. The app
labels `br400` "Wi-Fi Adapter" throughout the UI; only its internal class
name (`WebBridge`) and `DeviceType.BRIDGE` call it a bridge.

Full set of IDs observed:
`be459{,ble,wifi}`, `be479`, `be489{,ble,ble2,ble3,wb,wb2,wb3,wifi,wifi2,wifi3}`,
`be499{,ble,ble2,wb,wb2,wifi,wifi2}`, `be889{,ble,wifi}`,
`fe789{,ble,ble2,wb,wb2,wifi,wifi2}`, `gselent{,ble,wifi}`,
`gselsec{,ble,wifi}`, `sselent{,ble,wifi}`, `sselsec{,ble,wifi}`.

The suffix carries both transport and hardware generation. Generation 1
uses a bare prefix for the family and `ble` / `wifi` for the transport;
generations 2 and 3 ("McKinley" and "McKinley 2") substitute `wb<n>` for
the bare form, giving `wb2` / `ble2` / `wifi2` and `wb3` / `ble3` /
`wifi3`. Encode has three generations, Encode Plus and Encode Lever two,
and the rest one. Sense has no suffixed forms at all: it is always
`be479`.

`be489wb`, `be499wb` and `fe789wb` — `wb` with no generation number —
exist as constants but are referenced nowhere in 8.2.0 and no `DeviceType`
value maps to them. What `wb` stands for is not established anywhere in
the app; Schlage's retail SKU for the Encode deadbolt is BE489WB, and a
live `be489wifi` reports `modelName` `BE489WB1 619`.

The app distinguishes three predicates:

- `isWifiLock()` — the model *family* has WiFi capability (`be459`,
  `be489`, `be499`, `be889`, `fe789`, Selene). This is what
  `pyschlage.lock.Lock._is_wifi_lock()` reimplements, and it matches.
- `isRemote()` — the device is *currently* in WiFi mode, i.e. the suffix is
  `wifi`. For `be479` it falls back to "has related devices" (a bridge).
- `isBle()` — the suffix is `ble`, or for `be479`, no bridge is paired.

The Selene types are gated behind a `selene_lock` feature toggle, which is
`false` in the shipped 8.2.0 config.

### Model capabilities

Allegion groups the device types into families and gates features on the
family, not on the individual type. The groupings are defined in
`utilities/sense_device_utilities/DeviceTypeUtilityKt`:

| Predicate | Covers |
| --- | --- |
| `isDenaliFamilyLock` | every `be489` ID, all three generations |
| `isJackalopeFamilyLock` | every `be499` ID |
| `isEncodeLeverFamilyLock` | every `fe789` ID |
| `isWKDLock` | every `be459` ID |
| `isWaltonLock` | every `be889` ID |
| `isSeleneFamilyLock` / `isSeleneLock` | every `gselent`, `gselsec`, `sselent`, `sselsec` ID |
| `isSenseLock` | `be479` |
| `isEncodeFamilyLock` | everything except `be479` and `br400` |
| `isMckinleyLock` | the generation 2 and 3 IDs of Encode, Encode Plus and Encode Lever |

These are transport-agnostic, which is not obvious from the code.
`DeviceType.is()` special-cases the *base* enum value of each platform:
`is(DENALI)` runs `isDenali()`, which is
`this == DENALI || this == DENALI_BLE || this == DENALI_WIFI`. Only the
explicitly suffixed enum values (`DENALI_BLE`, `DENALI_WIFI`, ...) fall
through to plain equality. So `is(DENALI)` means "any first-generation
Encode, whatever transport", while `is(DENALI_BLE)` means exactly
`be489ble`. The `...BLELock` and `...WifiLock` predicates are built from
the suffixed values and really are transport-specific.

Feature gates found in the app. These are all app-side UI gating; the
service itself accepts the write regardless, so a gate is evidence the
lock will reject or ignore the setting, not proof of it:

| Feature | Gate |
| --- | --- |
| One-touch locking (lock-and-leave) | Every family **except** Selene and Sense Pro |
| Built-in alarm (mode + sensitivity) | Every family **except** Selene and Arrive |
| Built-in alarm on/off toggle | Selene only, in place of the above |
| Paging back through history | Encode, Encode Plus, Encode Lever, Arrive, Sense Pro — not Sense, not Selene |
| Linked locks (dual door) | Selene Secure always; Selene Entrance when `pairedLockStatus == 1` |
| Variable-length access codes | `supportedFeatures.vlac >= 1`, **or** any Sense Pro |
| Scheduled locking | `supportedFeatures.scheduledLocking >= 1`, and on Encode Plus also firmware major >= 4 |
| Activity alarm, WiFi mode | `supportedFeatures.activityAlarm >= 1` |
| Activity alarm, BLE mode | firmware major >= 11 on `be489ble`, >= 3 on `be489ble2` and `fe789ble2`, otherwise allowed |
| WiFi firmware update command | `supportedFeatures.wifiUpdateCommand >= 1` |
| Auto-lock delays | Per family, see [Auto-lock times](#auto-lock-times) |

"vlac" is variable-length access code. Without it, every code on the lock
is exactly `accessCodeLength` digits, chosen when the lock was
commissioned ("All future access codes you create for this lock will be
this length"); with it, each code may be 4 to 8 digits independently.

`getWiFiLockListL()`, the list `isLockInWifiMode()` matches against, holds
`be459wifi`, `be489wifi`, `be489wifi2`, `be489wifi3`, `be499wifi`,
`be499wifi2`, `be889wifi`, `fe789wifi`, `fe789wifi2`, `gselentwifi` and
`gselsecwifi` — the two Schlage-branded Selene WiFi IDs are missing, which
looks like an oversight in the app rather than a protocol rule.

### Device attributes

`GET devices/{id}` returns a device object. Top-level keys:
`deviceId`, `devicetypeId`, `name`, `modelName`, `physicalId`, `connected`,
`connectivityUpdated`, `created`, `lastUpdated`, `lastPersisted`, `role`,
`users[]`, `relatedDevices[]`, `attributes{}`.

A live device document also repeats `CAT`, `SAT`, `macAddress`,
`serialNumber` and `timezone` at the top level, alongside the copies
inside `attributes`. `pyschlage.lock.Lock` reads `CAT` from the top level,
which is why it finds it.

`attributes` keys the app binds, with the `pyschlage.lock.Lock` field that
exposes them. `Lock` reads every one of these from `attributes` except
`modelName`, which it takes from the top level, and `CAT`, as noted above:

| Attribute | Type | `Lock` field |
| --- | --- | --- |
| `accessCodeLength` | int | `access_code_length` |
| `actAlarmBuzzerEnabled` | int (bool) | — |
| `alarmSelection` | `AlarmState` enum | `alarm_mode` |
| `alarmSensitivity` | int | `alarm_sensitivity` |
| `autoLockTime` | int seconds | `auto_lock_time` |
| `batteryLevel` | int 0-100 | `battery_level` |
| `batteryLowState` | `BatteryState` enum | `battery_low_state` |
| `beeperEnabled` | int (bool) | `beeper_enabled` |
| `bleFirmwareVersion` | str | `ble_firmware_version` |
| `CAT` | str | `_cat` |
| `SAT` | str | `_sat` |
| `deviceUid` | str | — |
| `doorState` | `DoorState` enum | `door_state` |
| `dualDoorComm` | object | — |
| `keypadFirmwareVersion` | str | `keypad_firmware_version` |
| `lastTalkedTime` | ISO 8601 str | — |
| `lockAndLeaveEnabled` | int (bool) | `lock_and_leave_enabled` |
| `lockState` | `LockState` enum | `is_locked` / `is_jammed` |
| `lockStateMetadata` | object | `lock_state_metadata` |
| `macAddress` | str | `mac_address` |
| `mainFirmwareVersion` | str | `firmware_version` |
| `manufacturerName` | str | `manufacturer_name` |
| `maxSchedule` | str | — |
| `maxUserCodes` | int | `max_user_codes` |
| `modelName` | str | `model_name` |
| `opMode` | `LockMode` enum | `operating_mode` |
| `scheduleParams` | array | — |
| `serialNumber` | str | `serial_number` |
| `supportedFeatures` | object | — |
| `timezone` | double (offset, unit undetermined) | — |
| `wifiFirmwareVersion` | str | `wifi_firmware_version` |
| `M` | bool | — (app calls it `reachable`) |
| `L` | long | — (app calls it `time`) |

`supportedFeatures` is `{activityAlarm, scheduledLocking, vlac,
wifiUpdateCommand}`, all int-booleans, each treated as "on" when `>= 1`
and defaulted to `0` when absent. See
[Model capabilities](#model-capabilities) for what each one gates. `Lock`
has no field for it; it appears in `get_diagnostics()`.

Real API responses also contain attributes the app does not bind
(`actAlarmState`, `actuationCurrentMax`, `alarmState`, `batteryChangeDate`,
`batterySaverConfig`, `batterySaverState`, `diagnostics`, `firmwareUpdate`,
`homePosCurrentMax`, `mode`, `periodicDeepQueryTimeSetting`, `psPollEnabled`,
`wifiRssi`, `adminOnlyEnabled`, `hardwareVersion`, `profileVersion`). All
but `diagnostics` are listed in `Lock.get_diagnostics()`'s allowlist, so
`diagnostics` is redacted — deliberately, since it churns on every pushed
message (see [Push updates](#push-updates)).

`timezone`'s unit is unresolved, which is why `Lock` does not expose it.
Values seen are `-16` and `-20` on Encode locks and `-60` on a Sense.
Quarter-hour offsets would fit the first two (-4 h, -5 h) but not the
third (-15 h). The app only ever round-trips the value.

Writes go through `PUT devices/{id}` with `{"attributes": {...}}` and the
response is the full updated device, which is how
`pyschlage.lock.Lock._put_attributes` works.

### Enumerations

```
LockState       -1 INVALID, 0 UNLOCKED, 1 LOCKED, 2 JAMMED, 3 UNKNOWN,
                 4 MOTOR_JAMMED, 5 PASSAGE_MODE, 6 DEADLOCKED
DoorState        0 UNKNOWN, 1 OPEN, 2 CLOSE, 3 FAULTY
BatteryState    -1 UNKNOWN, 0 NORMAL, 1 LOW, 2 CRITICALLY_LOW
AlarmState      -1 INVALID, 0 DISABLED, 1 LOCK_UNLOCK, 2 TAMPER, 3 FORCED_ENTRY
LockMode         0 UNKNOWN, 1 SCHLAGE, 2 HOMEKIT, 3 SIMULTANEOUS
```

`pyschlage` maps `LOCKED` and `DEADLOCKED` to locked, `UNLOCKED` and
`PASSAGE_MODE` to unlocked, `JAMMED` and `MOTOR_JAMMED` to jammed, and
`UNKNOWN`, `INVALID` and an absent `lockState` to `None` for both
`is_locked` and `is_jammed`.

`SenseDeviceAttributes.Model` enumerates four `modelName` values —
`BE479CAM619`, `BE479CEN619`, `BE489CAM619`, `BE489CEN619` — and maps
anything else to `INVALID`. That is not the set of values that occur: a
live `be489wifi` reports `BE489WB1 619`. Separately,
`isValidModelName()`, used when parsing a commissioning QR code, accepts
any string containing `be489`, `be499`, `fe789`, `be459` or `be889`.

### Remote commands

`POST devices/{id}/commands` with `{"name": <command>, "data": {...}}`.
The complete command vocabulary (`enums/RemoteCommandType`):

| Command | Notes |
| --- | --- |
| `changelockstate` | Used by `pyschlage` for non-WiFi-family locks, i.e. whenever `Lock._is_wifi_lock()` is false: Sense, the adapter, and any unrecognized `devicetypeId`. WiFi-family locks are toggled with `PUT devices/{id}` instead. |
| `getaccesscodes` | |
| `addaccesscode` | Used by `pyschlage`. |
| `updateaccesscode` | Used by `pyschlage`. |
| `deleteaccesscode` | Used by `pyschlage`. |
| `deleteallaccesscodes` | |
| `gethistory` | |
| `clearhistory` | |
| `updatelockdatetime` | |
| `updatelockfirmware` | |
| `linklock` / `unlinklock` | Dual-door pairing. |
| `pinglock` / `pingbridge` | |
| `fwupdatebridge` | |
| `deletebridge` | |
| `getcredential` / `addcredential` / `updatecredential` / `deletecredential` / `deleteallcredential` | Key fobs and other credentials. |
| `updatefob` / `deletefob` / `deleteallfobs` | Fob-specific aliases. |

`data` fields seen across command bodies: `accessCode`, `accessCodeLength`,
`CAT`, `SAT`, `delayUpdate`, `deviceId`, `devicetypeId`,
`firmwareVersionURL`, `state`, `macAddress`, `numberOfRecords`,
`physicalId`, `startEpoch`, `userId`, `UUID`.

The synchronous response is
`{"result": <any>, "error": {"statusCode": int, "message": str}}`.

### Access codes

`GET devices/{id}/storage/accesscode/` returns objects with:

| Field | Type |
| --- | --- |
| `accesscodeId` | str (UUID) |
| `friendlyName` | str |
| `accessCode` | number, rendered zero-padded to `accessCodeLength` |
| `accessCodeLength` | int |
| `accessCodeSource` | int |
| `disabled` | bool / int |
| `activationSecs` | epoch seconds, `0` means "no start" |
| `expirationSecs` | epoch seconds, `0xFFFFFFFF` means "no end" |
| `schedule1`, `schedule2` | `{daysOfWeek, startHour, startMinute, endHour, endMinute}` |

`daysOfWeek` is a hex-string bitmask; bit 6 (`0x40`) is Sunday through bit 0
(`0x01`) Saturday, so `"7F"` is every day. `pyschlage.code.DaysOfWeek`
matches this.

Write bodies additionally carry `notificationEnabled` (int bool). The
notification itself is a separate object — see below.

`accessCodeSource` is not modelled by `pyschlage`.

### Credentials (key fobs)

`GET devices/{id}/storage/fob/?limit=N` returns credential objects, a
superset of access codes: all the access-code fields plus `credential`,
`credentialLength`, `credType` (int) and `fobId`. Writes go through the
`*credential` / `*fob` remote commands. `pyschlage` has no credential
support at all.

### Logs

`GET devices/{id}/logs?limit=N&sort=desc`. Entries:

| Field | Type |
| --- | --- |
| `logId` | str |
| `deviceId` | str |
| `type` | str |
| `createdAt` | ISO 8601 str |
| `updatedAt` | ISO 8601 str |
| `timestamp` | str |
| `message` | object **or** the literal string `"RESET_LOGS"` |

When `message` is an object:

| Field | Type |
| --- | --- |
| `eventCode` | int, see table below |
| `action` | int: `-1` unknown, `0` read, `1` action, `4` cleared |
| `accessorUuid` | str, `ffffffff-...` when not applicable |
| `keypadUuid` | str, `ffffffff-...` when not applicable |
| `fobId` | str |
| `linkedDeviceSn` | str |
| `secondsSinceEpoch` | int |

`message` is deserialized by a custom adapter: the string `"RESET_LOGS"`
is turned into an entry with `action = cleared` and no event code.
`pyschlage.log.LockLog.from_json` maps it to event code 24
(`LOGS_CLEARED`); `LockLog.event_code` is `-1` (`UNKNOWN_EVENT_CODE`) for
any other non-object `message`.

The app carries **two** names for each event code: an internal enum
identifier (`LockLog.Event`) and a user-facing string, chosen from
`res/raw/wifi_lock_log_messages.json` or `res/raw/ble_lock_log_messages.json`
depending on the lock's transport. `pyschlage.log.LOG_EVENT_TYPES` covers
exactly the same set of codes, but its strings follow neither name
consistently: 59 of the 85 are the sentence-cased enum identifier, 16 are
the WiFi display string instead (5, 12, 13, 33, 47, 48, 49, 66, 67, 71,
72, 74, 75, 81, 82, 83 — e.g. 48 `PASSAGE_MODE_ACTIVATED` is "Unlocked by
inside button"), and 10 are neither (34, 46, 64, 65, 68, 69, 70, 73, 84,
85 — e.g. 73 `DPS_ERROR` is "Door position sensor faulty", displayed as
"DPS Faulty"). Treat `LockLog.event_code` as the stable identifier and
`LockLog.message` as a convenience string.

| Code | App enum | WiFi display string | BLE display string |
| --- | --- | --- | --- |
| -1, 0 | `UNKNOWN` | Unknown | Unknown |
| 1 | `LOCKED_BY_KEYPAD` | Locked by Access Code | Locked by `%s` |
| 2 | `UNLOCKED_BY_KEYPAD` | Unlocked by Access Code | Unlocked by `%s` |
| 3 | `LOCKED_BY_THUMBTURN` | Locked by Thumbturn | |
| 4 | `UNLOCKED_BY_THUMBTURN` | Unlocked by Thumbturn | |
| 5 | `LOCKED_BY_SCHLAGE_BUTTON` | Locked by 1-Touch Locking | |
| 6 | `LOCKED_BY_MOBILE_DEVICE` | Locked by `%s` | |
| 7 | `UNLOCKED_BY_MOBILE_DEVICE` | Unlocked by `%s` | |
| 8 | `LOCKED_BY_TIME` | Locked by Auto Lock Delay | Locked by Time Delay |
| 9 | `UNLOCKED_BY_TIME` | Unlocked by Time Delay | |
| 10 | `LOCK_JAMMED` | Lock Jammed | Lock Jammed During Operation |
| 11 | `KEYPAD_DISABLED_INVALID_CODE` | Keypad Temporarily Disabled | Keypad Temporarily Disabled, Invalid Code |
| 12 | `ALARM_TRIGGERED` | Forced Entry Detected | |
| 13 | `RESERVED_FOR_POWERUP` | Reserved for power up | — |
| 14 | `ACCESS_CODE_USER_ADDED` | Access Code Added | Access Code `%1s` |
| 15 | `ACCESS_CODE_USER_DELETED` | Access Code Deleted | |
| 16 | `MOBILE_USER_ADDED` | Mobile User Added | |
| 17 | `MOBILE_USER_DELETED` | Mobile User Deleted | |
| 18 | `ADMIN_PRIVILEGE_ADDED` | Admin Privilege Added | |
| 19 | `ADMIN_PRIVILEGE_DELETED` | Admin Privilege Deleted | |
| 20 | `FIRMWARE_UPDATED` | Lock Firmware Updated | |
| 21 | `LOW_BATTERY_INDICATED` | Low Battery | Low Battery Indicated |
| 22 | `BATTERIES_REPLACED` | Batteries Replaced | |
| 23 | `FORCED_ENTRY_ALARM_SILENCED` | Forced Entry Alarm Silenced | |
| 24 | `ALL_LOGS_CLEARED` | All logs cleared | — |
| 25 | `LOCKED_BY_REMOTE` | Locked by remote | — |
| 26 | `UNLOCKED_BY_REMOTE` | Unlocked by remote | — |
| 27 | `HALL_SENSOR_COMM_ERROR` | Door Sensor Communication Error | |
| 28 | `FDR_FAILED` | FDR Failed | |
| 29 | `CRITICAL_BATTERY_STATE` | Critically Low Battery | Critical Battery Indicated |
| 30 | `ALL_ACCESS_CODE_DELETED` | All Access Codes Deleted | |
| 31 | `RESERVED_FOR_FUTURE` | Reserved for future | — |
| 32 | `FIRMWARE_UPDATE_FAILED` | Firmware Update Failed | |
| 33 | `BT_FW_DOWNLOAD_FAILED` | Bluetooth Firmware Download Failed | |
| 34 | `WIFI_FW_DOWNLOAD_FAILED` | Firmware Download Failed | WiFi Firmware Download Failed |
| 35 | `KEYPAD_DISCONNECTED` | Keypad Tamper Detected | Keypad disconnected from lock |
| 36 | `WIFI_AP_DISCONNECT` | WiFi AP disconnect | — |
| 37 | `WIFI_HOST_DISCONNECT` | WiFi host disconnect | Lock failed to communicate with cloud |
| 38 | `WIFI_AP_CONNECT` | WiFi AP connect | — |
| 39 | `WIFI_HOST_CONNECT` | WiFi host connect | Lock connected to cloud |
| 40 | `USER_DB_FAILURE` | Failed to add access code for `%1s` | |
| 41 | `RESET_SOURCE` | Reset Resource | — |
| 42 | `WIFI_POWER_POLICY_UPDATED` | WiFi power policy updated | — |
| 43 | `WIFI_ENTER_ROAMING` | WiFi enter roaming | — |
| 44 | `WIFI_EXIT_ROAMING` | WiFi exit roaming | — |
| 45 | `WIFI_HOST_CONNECT_ERROR` | WiFi host connect error | — |
| 46 | `WDOG_CHECKING_FAIL` | WDOG checking fail | — |
| 47 | `SCHEDULE_LOCKING` | Locked by Scheduled Locking | |
| 48 | `PASSAGE_MODE_ACTIVATED` | Unlocked by Inside Button | |
| 49 | `PASSAGE_MODE_DEACTIVATED` | Locked by Inside Button | |
| 51 | `ACTIVITY_ALARM_TRIGGERED` | Activity alarm triggered | |
| 52 | `UNLOCKED_BY_APPLE_KEY` | Unlocked by Apple Home Key | |
| 53 | `LOCKED_BY_APPLE_KEY` | Locked by Apple Home Key | |
| 54 | `MOTOR_JAMMED_ON_FAIL` | Internal malfunction | |
| 55 | `MOTOR_JAMMED_OFF_FAIL` | Internal malfunction | |
| 56 | `MOTOR_JAMMED_RETRIES_EXCEEDED` | Internal malfunction | |
| 57 | `THREAD_DISCONNECTED` | Thread disconnect | |
| 58 | `THREAD_CONNECTED` | Thread connect | |
| 59 | `LOCKED_BY_UWB` | Locked by UWB | |
| 60 | `UNLOCKED_BY_UWB` | Unlocked by Approach | |
| 61 | `UWB_ANTENNA_DISCONNECTED` | UWB Antenna Disconnected | |
| 62 | `LOCK_LOST_ACCURATE_TIME` | Lock lost accurate time | |
| 64 | `DEADLOCK_BY_KEYPAD` | Deadlocked by Access code | |
| 65 | `DEADLOCK_BY_MOBILE` | Deadlocked by `%s` | |
| 66 | `DEADLOCK_BY_FOB` | Deadlocked by Key Fob | Deadlocked by `%s` |
| 67 | `DEADLOCK_BY_KEYPAD_NFC` | Deadlocked by Keypad NFC | |
| 68 | `UNLOCKED_BY_IPB` | Unlocked by Internal push button | |
| 69 | `LOCKED_BY_IPB` | Locked by Internal push button | |
| 70 | `UNLOCKED_BY_REX` | Unlocked by Internal Lever | |
| 71 | `DPS_DOOR_OPEN` | Door Opened | |
| 72 | `DPS_DOOR_CLOSED` | Door Closed | |
| 73 | `DPS_ERROR` | DPS Faulty | |
| 74 | `LOCKED_BY_FOB` | Locked by Key Fob | Locked by `%s` |
| 75 | `UNLOCKED_BY_FOB` | Unlocked by Key Fob | Unlocked by `%s` |
| 76 | `UNLOCKED_BY_MECHANICAL_KEY` | Unlocked by Mechanical Key | |
| 78 | `KEY_FOB_USER_ADDED` | Key Fob Added | Key Fob For `%1s` Added |
| 79 | `KEY_FOB_USER_UPDATED` | Key Fob Updated | |
| 80 | `KEY_FOB_USER_DELETED` | Key Fob Deleted | |
| 81 | `LOCKED_BY_DUAL_DOOR` | Locked by Linked Lock | |
| 82 | `UNLOCKED_BY_DUAL_DOOR` | Unlocked by Linked Lock | |
| 83 | `DEADLOCKED_BY_DUAL_DOOR` | Deadlocked by Linked Lock | |
| 84 | `DUAL_DOOR_PAIRED` | `%1$s` is Linked to `%2$s` | |
| 85 | `DUAL_DOOR_UNPAIRED` | `%1$s` unlinked from `%2$s` | |
| 255 | `HISTORY_CLEARED` | Unknown | |

A blank BLE cell means the BLE string is the same as the WiFi one; `—`
means the code has no BLE mapping. Note that 24 (`ALL_LOGS_CLEARED`), not
255, is what the app shows for a cleared history; 255 renders as "Unknown".

### Notifications

`GET notifications?deviceId={id}` returns
`{notificationId, userId, deviceId, devicetypeId, notificationDefinitionId,
active, filterValue, createdAt, updatedAt}`. `notificationDefinitionId`
values in 8.2.0:

| Definition ID | `pyschlage.notification` constant |
| --- | --- |
| `onalarmstate` | `ON_ALARM` |
| `onactalarmstate` | `ON_ACTIVITY_ALARM` |
| `onbatterylowstate` | `ON_BATTERY_LOW` |
| `onstatelocked` | `ON_LOCKED` |
| `onstateunlocked` | `ON_UNLOCKED` |
| `onstatedeadlocked` | `ON_DEADLOCKED` |
| `onunlockstateaction` | `ON_UNLOCK_ACTION` |
| `ondoorclosedlockunlocked` | `ON_DOOR_CLOSED_LOCK_UNLOCKED` |
| `ondooropenedlocklocked` | `ON_DOOR_OPENED_LOCK_LOCKED` |
| `ondooropenedlockdeadlocked` | `ON_DOOR_OPENED_LOCK_DEADLOCKED` |

`pyschlage.notification.OFFLINE_24_HOURS` (`offline24hours`) does **not**
appear anywhere in the 8.2.0 APK. It may be server-side only, iOS-only, or
removed; it is kept because removing it would be a breaking change.

The `"{user_id}_{access_code_id}"` notification ID convention
`pyschlage.lock.Lock.get_access_codes` relies on is confirmed by the
template string `{{user-id}}_` in the app.

### Auto-lock times

The app offers a different set of auto-lock delays per model, read from
`res/values/arrays.xml`:

| Array | Chosen for | Seconds |
| --- | --- | --- |
| `auto_lock_keys_sense` | Sense | 0, 15, 30, 60, 120, 240 |
| `auto_lock_keys_encode_plus` | Encode Plus | 0, 15, 30, 60, 120, 240, 300 |
| `auto_lock_non_deadbolt_keys` | Encode Lever | 0, 5, 15, 30, 60, 120, 240, 360, 600 |
| `auto_lock_wkd_keys` | Arrive | 0, 15, 30, 60, 120, 240, 360, 600 |
| `auto_lock_walton_keys` | Sense Pro | 0, 30, 60, 120, 300, 600, 900, 1800 |
| `auto_lock_keys` | everything else: Encode, Selene | 0, 15, 30, 60, 120, 240, 360, 600 |

`LockSettingsViewModel.autoLockKeysForLockType()` picks in that order and
falls through to `auto_lock_keys`, so Encode and the Selene types share
the default list. The matching `auto_lock_*_values` arrays hold the
display labels, not the values written to the lock; the `*_keys` arrays
are the seconds.

`pyschlage.lock.AUTO_LOCK_TIMES` is the union of all six,
`(0, 5, 15, 30, 60, 120, 240, 300, 360, 600, 900, 1800)`, so
`set_auto_lock_time()` accepts values a given lock will reject: 5 seconds
on anything but an Encode Lever, 300 on anything but an Encode Plus or
Sense Pro, and 900 or 1800 on anything but a Sense Pro.

### Push updates

The app subscribes to MQTT over WebSockets (`rx/mqtt`,
`remote/SenseDeviceMqttConnectionManager`) and refreshes device state
from the pushed messages instead of polling.

Unlike the rest of this document, this section has been **checked
against a live account** (one `be489wifi`), so where the app's code and
the service disagree, what the service actually did is recorded.

#### Getting connection details

Both endpoints return the same `Topics` object:

```
{"clientId": str, "wssUri": str, "topics": [str, ...], "message": str}
```

| Endpoint | App method | Scope |
| --- | --- | --- |
| `GET wss?deviceId={id}` | `topicsFor(device)` | One lock. |
| `GET users/wss` | `topicsForUser()` | The whole account. This is the path the app uses. |

Both are called through `getApiWithIdToken()`, which adds
**`X-Web-Identity-Token: <Cognito ID token>`** on top of the usual
`Authorization: Bearer <access token>`. These are the only two paths in
the API that need more than the access token.

`GET users/wss` returning HTTP 400 is expected and retried
(`DeviceApiService.handleTopicsForUserResponse`); the app treats any
other status as fatal. A `Topics` with an empty `wssUri` or `clientId`
is rejected before connecting (`validateTopics`).

Observed from `GET users/wss`:

```
clientId: <the account's user id, verbatim>
wssUri:   wss://<prefix>-ats.iot.us-west-2.amazonaws.com/mqtt?<7 SigV4 params>
topics:   ["thincloud/users/<user id>/devices/#"]
```

**The account-wide endpoint returns a single MQTT wildcard**, not the
`reported` / `desired` / `delta` triple. Filtering the topic list by kind
therefore matches nothing and subscribes to nothing. The app agrees:
`Topics.reportedTopics()`, which `connectForMultipleDevices()` passes to
`subscribe()`, returns the list **unfiltered** — only the singular
`reportedTopic()` / `desiredTopic()` / `deltaTopic()` accessors match by
substring, and those serve the per-device endpoint. Subscribe to
everything the service returns.

Because the wildcard covers `devices/#`, one subscription covers every
device on the account.

#### Connecting

Paho MQTT via `MqttAndroidClient(context, wssUri, clientId, MemoryPersistence)`:

| Setting | Value |
| --- | --- |
| Protocol | MQTT 3.1.1 (`setMqttVersion(3)`) |
| Clean session | true |
| Keep-alive | 1800 s |
| Automatic reconnect | false |
| Connection timeout | 0 |
| Subscribe QoS | 0 |

The `wssUri` is pre-signed, so it is time limited; with automatic
reconnect off, a long-lived consumer has to re-fetch `Topics` and
reconnect. Retained and duplicate messages are dropped
(`RxMqtt.messageArrived`) — they are not fresh state.

Subscribe only once the broker has accepted the connection. Sending
SUBSCRIBE before CONNACK is processed appears to succeed and then
delivers nothing.

#### One consumer per account

`clientId` is the account's **user id**, identical on every request. MQTT
brokers evict an existing session when a new connection presents the same
client id, so only one push consumer per account can be connected at a
time, and a second one takes over rather than sharing.

The Schlage Home phone app is such a consumer. Observed with the app open
on the account owner's phone: the app and a second client disconnected
each other roughly every 7 seconds, each reconnecting about 1.4 seconds
later, until the app's session went away — 9 cycles over about a minute,
then a stable connection. Updates are still delivered in the gaps. This
is the mechanism behind the one-subscription-per-account behaviour, and
it means push alone is not a reliable substitute for polling: it degrades
whenever anyone in the household opens the app.

#### Messages

Published to `thincloud/users/{user_id}/devices/{device_id}` — note there
is no `/reported` suffix on the wildcard feed. Payload:

```
{"reported": { ...device document... }}
```

The inner document is a **complete** device document, the same shape as
`GET devices/{device_id}`: `deviceId`, `devicetypeId`, `name`,
`modelName`, `physicalId`, `serialNumber`, `macAddress`, `timezone`,
`connected`, `connectivityUpdated`, `users`, `relatedDevices`, `CAT`,
`SAT` and a full `attributes` map. Observed size: ~2.8 KB.

Three traps:

- **`name` and `modelName` are the device's own**, not the user's. A lock
  the REST API reports as `name` "Back Door" and `modelName`
  "BE489WB1 619" reports itself as "Encode" and "BE489WB". Applying a
  pushed document verbatim clobbers what the user configured.
- **The payload contains the device's `CAT` and `SAT` tokens**, and the
  `CAT` differs in every message. Anything that logs these payloads is
  logging credentials.
- `attributes.diagnostics` churns on every message, so a naive
  "did anything change?" comparison always says yes.

`lockStateMetadata.actionType` values seen in pushed messages include
`thumbTurn` and `deepQuery`; the latter is the service polling the lock,
not a user action.

The app deserializes the payload as `ReportedSenseDevice` (a single
`reported` field holding a `SenseDevice`), compares `lockState`,
`doorState`, firmware version and dual-door pairing status against what
it already has, and only then updates and publishes a
`SenseDeviceReportedEvent`.

## Bluetooth LE

The BLE protocol is Google's **uWeave** (the Weave/"Privet" RPC stack from
Brillo): CBOR-encoded RPC records over two GATT characteristics, with an
AES-EAX session and macaroon-based authorization. Errors come back as
uWeave error codes (`bluetooth/operations/support/UWeaveError`).

The app bundles `com.google.android.apps.weave.gcd.security` (SPAKE2 over
P-224, HMAC-SHA256, SHA-256), used for the initial out-of-box pairing with
the lock's PIN. Post-pairing operation does not need SPAKE2 — it uses the
cloud-issued tokens below.

### GATT profile

From `res/raw/sense_gatt_profile.json`:

| Service | UUID |
| --- | --- |
| uWeave Profile | `883f45ec-14cb-46aa-9864-9a4e782b33d0` |
| General | `7f0dee73-4a3f-4103-98e6-a46cd301bdfb` |

| Characteristic | UUID | Service |
| --- | --- | --- |
| `RxData` (lock → app, indications) | `26002998-e001-4812-8c08-5cd2afda0830` | uWeave |
| `TxData` (app → lock, write) | `ff530c78-cd50-4bb9-bbd4-0712f32b3796` | uWeave |
| `LeopardControlPoint` | `44ff6853-58db-4956-b298-5f6650dd61f6` | General |

Firmware update uses a separate profile
(`res/raw/firmware_gatt_profile.json`): service
`1f6b43aa-94de-4ba9-981c-da38823117bd` with `RxLength`
(`048d8799-695b-4a7f-a7f7-a4a1301587fe`), `RxData`
(`66b7c7fd-95a7-4f89-b0ad-38073a67c46c`), `RxCRC`
(`507efc3f-9231-438c-976a-fa04427f1f8f`) and `RxACKNAK`
(`1dc15719-0882-4bad-ab0f-9aeab0600c90`), plus `FWImageVersion`
(`bcde3b9e-3963-4123-b24d-42eccbb3a9c4`) in the General service.

The client subscribes to **indications** (not notifications) on `RxData`
and writes `TxData` with write-type `WRITE_TYPE_DEFAULT` (acknowledged
writes).

### Packet framing

Records are split across 20-byte GATT writes: a 1-byte header plus up to
**19** bytes of payload.

The header's high nibble is a 3-bit sequence counter that increments per
packet and wraps at 8. The low nibble is the packet role:

| Low nibble | Meaning |
| --- | --- |
| `0xC` | single packet — the whole record |
| `0x8` | first packet of a multi-packet record |
| `0x0` | middle packet |
| `0x4` | last packet |
| `0x1` | incoming connection request (lock-initiated) |

The connection-request packet is special-cased: its header is
`((counter + 8) << 4) | 0` and the rest of the packet is the raw
connection-request body, written as one unfragmented buffer.

On receive, the low nibble is read as `header & 0x0F`; `0xC` and `0x1` mean
"complete record", `0x8` starts a new buffer, `0x0` appends, `0x4` appends
and completes. Payload is always `packet[1:]`.

Records are additionally chunked into 1024-byte blocks above the packet
layer (`MAX_WRITE_BLOCK_SIZE`), which only matters for firmware images.

### Session establishment

Four steps, driven by the app's `BleOperations` state machine. `SAT` and
`CAT` are the base64-ish token strings from the cloud device attributes
(`attributes.SAT`, `attributes.CAT`), decoded to bytes.

**1. `SECURE_CONNECTION_REQUEST`** — write, unencrypted:

```
connection_request_byte
CBOR: 0, 1, 0, 2, 0, 20, 2      (seven top-level items, not an array)
client_random                   (12 random bytes)
```

The lock replies with at least 5 bytes of header followed by
`server_random`; `response[4]` is a non-zero-random-value flag and
`response[5:]` is `server_random`.

**2. `EXTEND_SAT`** — mint a session token from the SAT macaroon:

```python
sat_macaroon = Macaroon.decode(cbor_decode(SAT)[0])  # [caveats[], tag]
sat_tag = sat_macaroon.tag
sat_macaroon.caveats.append(bytes([0x14]))  # caveat 20
sat_macaroon.tag = hmac_tag(1)
write(cbor_encode(sat_macaroon.encode()))
```

where

```python
def hmac_tag(i):
    inner = cbor_encode(bytes([i]) + client_random + server_random)
    outer = cbor_encode(bytes([20]) + inner)
    return hmac_sha256(key=sat_tag, msg=outer)[:16]
```

A macaroon is CBOR `[array_of_caveats, tag_bytestring]`, optionally wrapped
in an outer byte string. Tags are HMAC-SHA256 truncated to 16 bytes.

In parallel, if `response[4] != 0`, the app asks the cloud for a fresh CAT:

```
POST {catStar}/catstar/{deviceId}
{"value": hex(bytes([response[4]]) + server_random)}
->  {"CAT": "<hex>"}
```

and uses that CAT in step 4 instead of the one from the device attributes.

**3. Session key derivation** — the lock's reply to step 2 must equal
`hmac_tag(2)`. The session secrets are then:

```python
ikm = bytes([2]) + client_random + server_random + sat_tag
salt = bytes(
    [
        0x00,
        0x8A,
        0x39,
        0x36,
        0x22,
        0x04,
        0x1F,
        0x5F,
        0x0F,
        0xC7,
        0x5D,
        0x97,
        0xDA,
        0xEE,
        0x6E,
        0x81,
        0xCB,
        0xBB,
        0x2B,
        0xC7,
        0x4F,
        0x9C,
        0xCC,
        0x91,
        0xE7,
        0x5E,
        0x77,
        0xA5,
        0x6B,
        0x4A,
        0x4B,
        0x05,
    ]
)
okm = hkdf_sha256(ikm, salt=salt, info=b"session key", length=32)
session_key = okm[:16]  # AES-128 key
session_id = okm[16:]  # 16 bytes, nonce prefix
```

The salt is hardcoded in the app
(`bluetooth/operations/SenseBlePeripheral.generateSessionData`).

**4. `AUTHORIZE_CAT`** — the first encrypted record:

```
CBOR map {1: 5, 2: 1, 16: {0: 2, 1: 0, 2: <cat_bytes>}}
```

After this the session is usable and operation-specific RPCs follow.

### Record encryption

Every record after the session key exists is AES-128-EAX with a 96-bit tag:

```python
nonce = session_id + bytes([direction]) + b"\x00\x00" + bytes([counter])
# direction 0x01 = app -> lock, 0x03 = lock -> app
# counter starts at 1 and increments per record, per direction
```

Counters reset to 1 whenever the connection drops. The ciphertext written
is `EAX(key=session_key, nonce=nonce, mac_size=96)` over the CBOR record,
with the tag appended; `pycryptodome`'s `AES.MODE_EAX` is wire-compatible
with BouncyCastle's `EAXBlockCipher` used by the app.

A second, keyless variant exists for commissioning payloads:
`AES-EAX` with a 1-byte nonce of `0x00` (encrypt) or `0x01` (decrypt).

### RPC envelope

The record is a CBOR map with integer keys:

| Key | Meaning |
| --- | --- |
| 1 | API id |
| 2 | Request id |
| 3 | Error map, present only on failures |
| 4 | *(inside the error map)* error code |
| 16 | Params |
| 17 | Result |

API ids observed: `5` (authorization / CAT), `6` (lock-state read),
`8` (trait get/set).

For `8`, the params map is `{0: trait, 1: attribute}` for a read and
`{0: trait, 1: attribute, 2: {0: value, 1: user_id_bytes}}` for a write
(`user_id_bytes` is the 16-byte big-endian account UUID).

A successful response nests the payload as `result[17][17]`; the lock-state
read returns a map directly under `result[17]`.

### Traits and attribute IDs

Trait ids: `1` lock data, `5` lock config group, `6` access-point params.

Lock data (trait 1):

| Attribute | Direction | Meaning |
| --- | --- | --- |
| 0 | write | set lock state (value is a `LockState` ordinal) |
| 2 | read | manufacturer name |
| 3 | read | model name |
| 4 | read | serial number |
| 5 | read | main firmware version |
| 6 | write | set current time (epoch seconds) |
| 7 | read | current time |
| 12 | read | battery level |
| 15 | read | extended firmware versions |

Lock config group (trait 5) — setters are consistently `getter - 1`:

| Read | Write | Setting |
| --- | --- | --- |
| 3 | 2 | beeper enabled |
| 5 | 4 | auto-lock time |
| 9 | 8 | alarm selection |
| 11 | 10 | alarm sensitivity |
| 13 | 12 | lock-and-leave enabled |
| 15 | — | access code length |
| 21 | 20 | timezone |
| 27 | 23 / 26 | operating mode (`23` normally, `26` to enable simultaneous mode, `27` on Sense Pro) |
| — | 28 | max user codes query |

Keys in a lock-state response map:

| Key | Meaning |
| --- | --- |
| 0 | lock status (`LockState`) |
| 12 | battery state (`BatteryState`) |
| 14 | alarm selection (`AlarmState`) |
| 17 | operating mode (`LockMode`) |
| 21 | battery level |
| 25 | door state (`DoorState`) |
| 128 | dual-door pairing state |
| 129 | dual-door paired MAC address |
| 130 | dual-door config |

Other param keys used during commissioning: `0` commission status /
SSID / host, `1` password, `2` WiFi security type (value `1` =
personal), `7` dual-door config, `10` network RSSI.

### Operation sequences

Each app operation is a small state machine over `BleOperations`. The
lock/unlock path, for example, is:

```
connect -> discover services -> subscribe RxData indications
  -> SECURE_CONNECTION_REQUEST
  -> EXTEND_SAT            (+ catstar fetch if response[4] != 0)
  -> AUTHORIZE_CAT
  -> LOCK_UNLOCK_COMMAND   (trait 1, attribute 0, value = LockState ordinal)
  -> parse lock state / battery / alarm / door state from result
  -> unsubscribe, disconnect
```

Operations the app implements, each a class in
`com.allegion.leopard.bluetooth.operations`:

commissioning (`BleCommission`), lock/unlock (`BleLockUnlock`), deadlock,
lock state (`BleLockState`), lock information (`BleLockInformation`),
settings read/write (`BleSaveSettings`), access codes (`BleSaveAccessCode`,
`BleDeleteAccessCode`, `BleDeleteAllAccessCode`, `BleReadAccessCodeUsers`),
credentials (`BleAddCredential`, `BleDeleteCredential`,
`BleDeleteAllCredential`, `BleReadCredentialUsers`), history
(`BleReadLogGroup`), time (`BleUpdateTime`), WiFi provisioning
(`BleStartScanForWifiNetworks`, `BleReadWifiNetworks`,
`BleConfigureWiFiCredentials`, `BleGetAccessPointInfo`,
`BleGetLockWifiMacAddress`, `BleGetJITRStatus`), firmware (`BleFirmware`,
`BleSendFWUpdateURL`), operating mode (`BleFetchLockMode`,
`BleEnableSimultaneousMode`), dual door (`BleDualDoorPairingSetup`,
`BleDualDoorPairing`, `BleDualDoorUnpairing`), delete (`BleDelete`), and
wake-up (`BleWakeUp`).

Device discovery scans for the uWeave service UUID and matches the lock by
MAC address (`attributes.macAddress`); `MultiLockScanner` / `ScanLocksManager`
handle multiple locks in range.
