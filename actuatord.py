#!/usr/bin/env python3
import json
import time
import threading
import sys

import serial
import paho.mqtt.client as mqtt

BROKER = "127.0.0.1"
PORT = 1883
KEEPALIVE = 60

TOPIC_CMD = "iotcmd"
TOPIC_STATUS = "iotactuatorstatus"

SERIALDEV = "/dev/ttyACM0"
SERIALBAUD = 57600
SERIALTIMEOUT = 0.8

ALLOWED = {
    "UNLOCK", "LOCK",
    "VENTON", "VENTOFF",
    "FIREALARMON", "FIREALARMOFF",
    "INTRUSIONALARMON", "INTRUSIONALARMOFF",
    "AUTHWAIT30", "AUTHOK", "AUTHFAIL",
    "PING",
}

ser = None
serlock = threading.Lock()

def log(*a):
    print(*a, flush=True)

def open_serial():
    global ser
    try:
        ser = serial.Serial(SERIALDEV, SERIALBAUD, timeout=SERIALTIMEOUT)
        try:
            ser.reset_input_buffer()
        except Exception:
            pass
        log("[actuatord] serial open OK", SERIALDEV, SERIALBAUD)
        return True
    except Exception as e:
        ser = None
        log("[actuatord] serial open FAIL", SERIALDEV, repr(e))
        return False

def serial_send_cmd(cmd: str) -> str:
    if ser is None:
        return "ERR;SERIALNOTOPEN"

    out = f"CMD;{cmd}\n".encode("utf-8")

    with serlock:
        try:
            # clear stale bytes so next readline corresponds to this command
            try:
                ser.reset_input_buffer()
            except Exception:
                pass

            ser.write(out)
            ser.flush()

            raw = ser.readline()
            if not raw:
                return ""
            return raw.decode("utf-8", errors="replace").strip()
        except Exception as e:
            return f"ERR;SERIALIO;{repr(e)}"

def publish_status(mqttc, payload: dict):
    mqttc.publish(TOPIC_STATUS, json.dumps(payload), qos=0, retain=False)

def on_connect(mqttc, userdata, flags, reason_code, properties=None):
    log("[actuatord] mqtt connected rc=", reason_code, "subscribing", TOPIC_CMD)
    mqttc.subscribe(TOPIC_CMD, qos=0)

    # announce presence (this is the message you MUST see in mosquitto_sub)
    publish_status(mqttc, {
        "type": "status",
        "msg": "actuatord_online",
        "ts": int(time.time()),
        "serialdev": SERIALDEV,
        "serialbaud": SERIALBAUD,
        "allowed_count": len(ALLOWED),
    })

def on_message(mqttc, userdata, msg):
    ts = int(time.time())
    text = msg.payload.decode("utf-8", errors="replace")
    log("[actuatord] RX", msg.topic, text)

    try:
        data = json.loads(text)
    except Exception:
        publish_status(mqttc, {"type": "error", "msg": "badjson", "topic": msg.topic, "ts": ts, "raw": text[:200]})
        return

    cmd = str(data.get("cmd", "")).strip().upper()
    src = str(data.get("src", "")).strip() or "unknown"

    if cmd not in ALLOWED:
        publish_status(mqttc, {"type": "error", "msg": "cmd_not_allowed", "cmd": cmd, "src": src, "ts": ts})
        return

    reply = serial_send_cmd(cmd)
    log("[actuatord] SERIAL", cmd, "->", reply)

    publish_status(mqttc, {"type": "ack", "cmd": cmd, "src": src, "reply": reply, "ts": ts})

def main():
    open_serial()

    mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="actuatord-rpi4")
    mqttc.on_connect = on_connect
    mqttc.on_message = on_message

    try:
        mqttc.connect(BROKER, PORT, KEEPALIVE)
    except Exception as e:
        log("[actuatord] mqtt connect FAIL", repr(e))
        sys.exit(2)

    log("[actuatord] loop_forever")
    mqttc.loop_forever()

if __name__ == "__main__":
    main()

