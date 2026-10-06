#!/usr/bin/env python3
import json
import time
import threading

import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
PORT = 1883
KEEPALIVE = 60

TOPIC_EVENTS = "iotevents"
TOPIC_TELE = "iottelemetry"
TOPIC_CMD = "iotcmd"

# tuning
AUTORELOCK_SECONDS = 5
PIR_RETRIGGER_BLOCK_S = 10
FIRE_MQRAW_THRESHOLD = 300  # prilagodi kad testiraš dim/plin

# internal state
authwait_active = False
authwait_started_at = 0.0
last_pir = 0

fire_active = False

def publish_cmd(mqttc, cmd: str, src: str, extra: dict | None = None):
    p = {"cmd": cmd, "src": src}
    if extra:
        p.update(extra)
    mqttc.publish(TOPIC_CMD, json.dumps(p), qos=0, retain=False)

def schedule_relock(mqttc):
    def worker():
        time.sleep(AUTORELOCK_SECONDS)
        publish_cmd(mqttc, "LOCK", "rules")
        print("AUTO LOCK")
    threading.Thread(target=worker, daemon=True).start()

def start_authwait(mqttc, reason: str):
    global authwait_active, authwait_started_at
    now = time.time()
    if authwait_active:
        return
    if (now - authwait_started_at) < PIR_RETRIGGER_BLOCK_S:
        return
    publish_cmd(mqttc, "AUTHWAIT30", "rules", {"reason": reason})
    print("AUTHWAIT30", reason)
    authwait_active = True
    authwait_started_at = now

def stop_authwait():
    global authwait_active
    authwait_active = False

def handle_event(mqttc, payload: dict):
    etype = str(payload.get("type", "")).strip().upper()

    if etype == "RFIDUNAUTH":
        start_authwait(mqttc, "RFIDUNAUTH")
        return

    if etype == "RFIDAUTH":
        publish_cmd(mqttc, "AUTHOK", "rules")
        publish_cmd(mqttc, "UNLOCK", "rules")
        print("RFIDAUTH -> AUTHOK + UNLOCK")
        stop_authwait()
        schedule_relock(mqttc)
        return

    # Bonus: tvoj event ALARMOFFREQ (treat as intrusion off request)
    if etype == "ALARMOFFREQ":
        publish_cmd(mqttc, "INTRUSIONALARMOFF", "rules")
        print("ALARMOFFREQ -> INTRUSIONALARMOFF")
        return

def handle_telemetry(mqttc, payload: dict):
    global last_pir, fire_active

    # PIR rising edge 0->1
    try:
        pir = int(payload.get("pir", 0) or 0)
    except Exception:
        pir = 0

    if pir == 1 and last_pir == 0:
        start_authwait(mqttc, "PIR")
    last_pir = pir

    # Fire by mqraw threshold (ne oslanjamo se na state="ALARM")
    try:
        mqraw = int(payload.get("mqraw", 0) or 0)
    except Exception:
        mqraw = 0

    fire_now = mqraw >= FIRE_MQRAW_THRESHOLD

    if fire_now and not fire_active:
        # FIRE ON -> pali alarm + ventilaciju
        publish_cmd(mqttc, "FIREALARMON", "rules", {"mqraw": mqraw})
        publish_cmd(mqttc, "VENTON", "rules")
        print("FIREALARMON mqraw=", mqraw, " + VENTON")
        fire_active = True

    elif (not fire_now) and fire_active:
        # FIRE OFF -> gasi alarm + ventilaciju
        publish_cmd(mqttc, "FIREALARMOFF", "rules", {"mqraw": mqraw})
        publish_cmd(mqttc, "VENTOFF", "rules")
        print("FIREALARMOFF mqraw=", mqraw, " + VENTOFF")
        fire_active = False

def on_connect(client, userdata, flags, reason_code, properties=None):
    print("connected rc=", reason_code)
    client.subscribe(TOPIC_EVENTS, qos=0)
    client.subscribe(TOPIC_TELE, qos=0)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8", errors="replace"))
    except Exception:
        return

    if msg.topic == TOPIC_EVENTS:
        handle_event(client, payload)
    elif msg.topic == TOPIC_TELE:
        handle_telemetry(client, payload)

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, KEEPALIVE)
    print("[iot_rules] running, publishing to", TOPIC_CMD)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

if __name__ == "__main__":
    main()
