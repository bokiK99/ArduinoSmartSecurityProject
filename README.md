# Smart Security System
An end-to-end "mini SCADA" for a single room. It monitors motion, air quality and RFID access. It stores everything in a database, applies automatic rules to control a lock, a fan and an alarm, and offers a web dashboard with manual override

## Architecture

Data flows through four layers: sensors → gateway → backend (MQTT + DB + rules) → actuators + web UI.
1) The sensor Arduino reads the PIR, MQ135 and RFID inputs and sends text lines over UART.

2) The Croduino (ESP8266) converts those lines to JSON and publishes them over MQTT.

3) The Raspberry Pi runs the Mosquitto broker, the MariaDB database and four Python services. They log the data, apply the rules, drive the actuators and serve the web interface.

4) The actuator Arduino receives commands from the Raspberry Pi over serial and controls the fan, lock, buzzer and LCD.

5) The web UI connects to the Raspberry Pi over WebSocket to display live data and send manual commands.


## MQTT topics:

1) **iottelemetry**: sensor readings.

2) **iotevents**: RFID and alarm events.

3) **iotcmd**: commands to actuators.

4) **iotactuatorstatus**: acknowledgements from the actuator side.

## Components

### Sensor Arduino

Hardware: PIR on D2, MQ135 on A0, RC522 RFID over SPI (SS 10, RST 9).

States: IDLE, WAIT_FOR_CARD, ALARM.

Flow: motion in IDLE sends E;PIR:1 and starts a 30 s wait. If no authorized card arrives in time, it enters ALARM.

RFID: the scanned UID is compared with a master tag. Every scan sends E;RFID_DEBUG. A match sends E;RFID_AUTH. A mismatch sends E;RFID_UNAUTH.

Master-tag follow-up: in WAIT_FOR_CARD it also sends E;UNLOCK_REQ. In ALARM it also sends E;ALARM_OFF_REQ.

Telemetry: every 2 s, T;MQRAW:..;MQAVG:..;PIR:..;STATE:...

Link: UART at 57600 baud to the Croduino.

### Croduino Nova2 (ESP8266 gateway)

It joins Wi-Fi and connects to the broker on the Raspberry Pi (port 1883). It parses the UART lines and republishes them as JSON:

Telemetry goes to iottelemetry, e.g. {"mqraw":123,"mqavg":120,"pir":1,"state":"ALARM"}.

Events go to iotevents, e.g. {"type":"RFIDAUTH","uid":"606B4F55"}.

RFID_DEBUG is ignored.

### Raspberry Pi services

**mqtttodb.py**: subscribes to iottelemetry and iotevents. It inserts the data into the telemetry_v2 and events tables in MariaDB.

**iot_rules.py**: the automatic rule engine. It listens to telemetry and events and publishes commands to iotcmd.

**actuatord.py**: validates each command against a whitelist. It sends CMD;<CMD> to the actuator Arduino on /dev/ttyACM0 at 57600 baud. It publishes the Arduino's reply (e.g. ACK;UNLOCK) to iotactuatorstatus.

**ws_scada.py**: a WebSocket server at /ws. It pushes the latest telemetry and the last 10 events every second. It accepts commands from the UI, logs them in the commands table and publishes them to iotcmd.

**index.html** is served by Apache or Nginx. It connects to ws://<RPi-IP>:8888/ws, shows status, telemetry and events, and has buttons such as UNLOCK and ALARM OFF.

### Rule engine (iot_rules.py)

**<ins>Parameters:</ins>**

AUTORELOCK_SECONDS = 5: auto-lock delay after unlock.

PIR_RETRIGGER_BLOCK_S = 10: minimum gap between auth-wait windows.

FIRE_MQRAW_THRESHOLD = 300: MQ135 raw value that triggers the fire alarm.

**<ins>Rules</ins>:**

Auth wait: a PIR rising edge (0→1) or an RFIDUNAUTH event sends AUTHWAIT30.

Valid card: RFIDAUTH sends AUTHOK and UNLOCK, then schedules a LOCK after 5 s.

Alarm off: ALARMOFFREQ sends INTRUSIONALARMOFF.

Fire: MQRAW ≥ 300 sends FIREALARMON and VENTON. Dropping below 300 sends FIREALARMOFF and VENTOFF.

### Actuator Arduino

Outputs: fan relay on D2, servo lock on D3, buzzer on D6, I2C LCD 20x4.

Commands: VENTON/OFF, UNLOCK/LOCK, FIREALARMON/OFF, INTRUSIONALARMON/OFF, AUTHWAIT30, AUTHOK, AUTHFAIL, PING.

Countdown: AUTHWAIT30 starts a 30 s countdown on the LCD. AUTHOK cancels it, switches off the intrusion alarm and may leave the lock open. AUTHFAIL cancels it and switches on the intrusion alarm.

Timeout event: if the countdown expires, it sends EVT;AUTHTIMEOUT;INTRUSIONALARMON over serial.

## Scenarios

1) **Authorized entry**: motion → 30 s wait → valid card → unlock → auto-lock after 5 s.

2) **Intrusion**: motion → no valid card, or an unknown card → intrusion alarm, logged to the database.

3) **Fire or smoke**: MQRAW ≥ 300 → fire alarm and fan on, until the value falls below 300.

4) **Manual override**: web button → WebSocket → iotcmd → actuator.

## Images:

### Security system:
<img width="1200" height="1600" alt="17a23601-4084-437e-be65-4f97791b1046" src="https://github.com/user-attachments/assets/102d4837-3c6a-4367-a78f-08dfe1ff317c" />

### Web dashboard (image 1):
<img width="1918" height="884" alt="stranica_1" src="https://github.com/user-attachments/assets/b99ad2de-0c92-4d40-876d-a4d72283918f" />

### Web dashboard (image 2):
<img width="1917" height="882" alt="stranica_2" src="https://github.com/user-attachments/assets/1ddabe3a-9e0f-4c67-88ef-3f1a954a70fc" />









