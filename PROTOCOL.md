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

| Prefix | Product | `pyschlage.device.DeviceType` |
| --- | --- | --- |
| `br400` | WiFi bridge | `BRIDGE` |
| `be459` | Arrive (internally "WKD") | `ARRIVE` |
| `be479` | Sense | `SENSE` |
| `be489` | Encode ("Denali") | `ENCODE` |
| `be499` | Encode Plus ("Jackalope") | `ENCODE_PLUS` |
| `be889` | Sense Pro ("Walton") | `SENSE_PRO` |
| `fe789` | Encode Lever | `ENCODE_LEVER` |
| `gselent` | Gainsborough Selene Entrance | **missing** |
| `gselsec` | Gainsborough Selene Secure | **missing** |
| `sselent` | Schlage Selene Entrance | **missing** |
| `sselsec` | Schlage Selene Secure | **missing** |

Suffixes: bare (family), `ble`, `wifi`, `wb` (WiFi bridge), and generation
numbers `2` / `3` ("McKinley" revisions). Full set observed:
`be459{,ble,wifi}`, `be479`, `be489{,ble,ble2,ble3,wb,wb2,wb3,wifi,wifi2,wifi3}`,
`be499{,ble,ble2,wb,wb2,wifi,wifi2}`, `be889{,ble,wifi}`,
`fe789{,ble,ble2,wb,wb2,wifi,wifi2}`, `gselent{,ble,wifi}`,
`gselsec{,ble,wifi}`, `sselent{,ble,wifi}`, `sselsec{,ble,wifi}`.

The app distinguishes three predicates:

- `isWifiLock()` — the model *family* has WiFi capability (`be459`,
  `be489`, `be499`, `be889`, `fe789`, Selene). This is what
  `pyschlage.lock.Lock._is_wifi_lock()` reimplements, and it matches.
- `isRemote()` — the device is *currently* in WiFi mode, i.e. the suffix is
  `wifi`. For `be479` it falls back to "has related devices" (a bridge).
- `isBle()` — the suffix is `ble`, or for `be479`, no bridge is paired.

The Selene types are gated behind a `selene_lock` feature toggle, which is
`false` in the shipped 8.2.0 config.

### Device attributes

`GET devices/{id}` returns a device object. Top-level keys:
`deviceId`, `devicetypeId`, `name`, `modelName`, `physicalId`, `connected`,
`connectivityUpdated`, `created`, `lastUpdated`, `lastPersisted`, `role`,
`users[]`, `relatedDevices[]`, `attributes{}`.

`attributes` keys the app binds, with the `pyschlage.lock.Lock` field that
exposes them:

| Attribute | Type | `Lock` field |
| --- | --- | --- |
| `accessCodeLength` | int | — |
| `actAlarmBuzzerEnabled` | int (bool) | — |
| `alarmSelection` | `AlarmState` enum | — |
| `alarmSensitivity` | int | — |
| `autoLockTime` | int seconds | `auto_lock_time` |
| `batteryLevel` | int 0-100 | `battery_level` |
| `batteryLowState` | `BatteryState` enum | — |
| `beeperEnabled` | int (bool) | `beeper_enabled` |
| `bleFirmwareVersion` | str | — |
| `CAT` | str | `_cat` |
| `SAT` | str | — |
| `deviceUid` | str | — |
| `doorState` | `DoorState` enum | — |
| `dualDoorComm` | object | — |
| `keypadFirmwareVersion` | str | — |
| `lastTalkedTime` | ISO 8601 str | — |
| `lockAndLeaveEnabled` | int (bool) | `lock_and_leave_enabled` |
| `lockState` | `LockState` enum | `is_locked` / `is_jammed` |
| `lockStateMetadata` | object | `lock_state_metadata` |
| `macAddress` | str | `mac_address` |
| `mainFirmwareVersion` | str | `firmware_version` |
| `manufacturerName` | str | — |
| `maxSchedule` | str | — |
| `maxUserCodes` | int | — |
| `modelName` | str | `model_name` |
| `opMode` | `LockMode` enum | — |
| `scheduleParams` | array | — |
| `serialNumber` | str | — |
| `supportedFeatures` | object | — |
| `timezone` | double (offset) | — |
| `wifiFirmwareVersion` | str | — |
| `M` | bool | — (app calls it `reachable`) |
| `L` | long | — (app calls it `time`) |

`supportedFeatures` is `{activityAlarm, scheduledLocking, vlac,
wifiUpdateCommand}`, all int-booleans.

Real API responses also contain attributes the app does not bind
(`actAlarmState`, `actuationCurrentMax`, `alarmState`, `batteryChangeDate`,
`batterySaverConfig`, `batterySaverState`, `diagnostics`, `firmwareUpdate`,
`homePosCurrentMax`, `mode`, `periodicDeepQueryTimeSetting`, `psPollEnabled`,
`wifiRssi`, `adminOnlyEnabled`, `hardwareVersion`, `profileVersion`). These
are listed in `Lock.get_diagnostics()`'s allowlist.

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

`pyschlage` only interprets `lockState` values 0, 1 and 2. States 4, 5 and
6 are therefore reported as "unlocked and not jammed", which is wrong for
a deadbolt reporting `DEADLOCKED`, a lock in passage mode, and a motor
jam.

`modelName` values the app recognises explicitly: `BE479CAM619`,
`BE479CEN619`, `BE489CAM619`, `BE489CEN619`.

### Remote commands

`POST devices/{id}/commands` with `{"name": <command>, "data": {...}}`.
The complete command vocabulary (`enums/RemoteCommandType`):

| Command | Notes |
| --- | --- |
| `changelockstate` | Used by `pyschlage` for BLE locks. |
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
`pyschlage.log.LockLog.from_json` indexes `message` unconditionally and
raises `TypeError` on such an entry, taking `Lock.logs()` down with it.

The app carries **two** names for each event code: an internal enum
identifier (`LockLog.Event`) and a user-facing string, chosen from
`res/raw/wifi_lock_log_messages.json` or `res/raw/ble_lock_log_messages.json`
depending on the lock's transport. `pyschlage.log.LOG_EVENT_TYPES` mirrors
the internal enum names.

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
| `onactalarmstate` | **missing** |
| `onbatterylowstate` | `ON_BATTERY_LOW` |
| `onstatelocked` | `ON_LOCKED` |
| `onstateunlocked` | `ON_UNLOCKED` |
| `onstatedeadlocked` | **missing** |
| `onunlockstateaction` | `ON_UNLOCK_ACTION` |
| `ondoorclosedlockunlocked` | **missing** |
| `ondooropenedlocklocked` | **missing** |
| `ondooropenedlockdeadlocked` | **missing** |

`pyschlage.notification.OFFLINE_24_HOURS` (`offline24hours`) does **not**
appear anywhere in the 8.2.0 APK. It may be server-side only, iOS-only, or
removed; it is kept because removing it would be a breaking change.

The `"{user_id}_{access_code_id}"` notification ID convention
`pyschlage.lock.Lock.get_access_codes` relies on is confirmed by the
template string `{{user-id}}_` in the app.

### Auto-lock times

The app offers a different set of auto-lock delays per model, read from
`res/values/arrays.xml`:

| Array | Seconds |
| --- | --- |
| `auto_lock_keys` (Encode, Encode Lever) | 0, 15, 30, 60, 120, 240, 360, 600 |
| `auto_lock_keys_encode_plus` | 0, 15, 30, 60, 120, 240, 300 |
| `auto_lock_keys_sense` | 0, 15, 30, 60, 120, 240 |
| `auto_lock_non_deadbolt_keys` | 0, 5, 15, 30, 60, 120, 240, 360, 600 |
| `auto_lock_walton_keys` (Sense Pro) | 0, 30, 60, 120, 300, 600, 900, 1800 |
| `auto_lock_wkd_keys` (Arrive) | 0, 15, 30, 60, 120, 240, 360, 600 |

`pyschlage.lock.AUTO_LOCK_TIMES` is
`(0, 5, 15, 30, 60, 120, 240, 300, 360, 600)` — the union of every list
except Sense Pro's, so **900 and 1800 are rejected even though Sense Pro
accepts them**.

### Push updates

The app subscribes to MQTT over WebSockets (`rx/mqtt`,
`remote/SenseDeviceMqttConnectionManager`) and refreshes device state
from the pushed messages instead of polling. `pyschlage` has no
equivalent; callers poll `Lock.refresh()`.

Both endpoints return the same `Topics` object:

```
{"clientId": str, "wssUri": str, "topics": [str, ...], "message": str}
```

Topic names are matched by substring: one containing `reported`, one
`desired`, one `delta` — the AWS IoT device-shadow topic triple.

There are **two** ways to get one, and they are not equivalent:

| Endpoint | App method | Scope |
| --- | --- | --- |
| `GET wss?deviceId={id}` | `topicsFor(device)` | One lock. In practice the service allows only one lock and one subscription per account at a time, which makes this of little use to an account with more than one lock or more than one client. |
| `GET users/wss` | `topicsForUser()` | The whole account. `topics` covers every lock, and `connectForMultipleDevices()` subscribes to all of `topics.reportedTopics()` over a **single** MQTT connection with one `clientId`. This is the path the app actually uses. |

Two details that will bite an implementation:

- Both `wss` endpoints are called through `getApiWithIdToken()`, which
  adds **`X-Web-Identity-Token: <Cognito ID token>`** on top of the usual
  `Authorization: Bearer <access token>`. `pyschlage.auth.Auth.request`
  does not send that header, so these are the only two paths in the API
  that need more than the standard credentials.
- `GET users/wss` returning HTTP 400 is expected and retried
  (`DeviceApiService.handleTopicsForUserResponse`); the app treats any
  other status as fatal. A `Topics` with an empty `wssUri` or `clientId`
  is rejected before connecting (`validateTopics`).

The connection itself uses a 1800-second keep-alive with automatic
reconnect disabled, so the client is responsible for re-establishing it.

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
