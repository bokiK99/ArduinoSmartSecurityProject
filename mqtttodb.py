#!/usr/bin/env python3
import json
import sys

import MySQLdb as mdb
import paho.mqtt.client as mqtt

# ---------------- MQTT ----------------
BROKER = "127.0.0.1"
PORT = 1883
KEEPALIVE = 60

TOPIC_TELE = "iottelemetry"
TOPIC_EVT = "iotevents"
TOPICS = [(TOPIC_TELE, 0), (TOPIC_EVT, 0)]

# ---------------- DB ----------------
DBHOST = "localhost"
DBUSER = "sensorwriter"
DBPASS = "password"
DBNAME = "sensors"

def db_connect():
    return mdb.connect(DBHOST, DBUSER, DBPASS, DBNAME)

def insert_telemetry_v2(p):
    con = db_connect()
    try:
        cur = con.cursor()
        sql = """
            INSERT INTO telemetry_v2 (ts, mqraw, mqavg, pir)
            VALUES (NOW(), %s, %s, %s)
        """
        cur.execute(sql, (
            p.get("mqraw"),
            p.get("mqavg"),
            p.get("pir"),
        ))
        con.commit()
    finally:
        con.close()

def insert_event(p):
    con = db_connect()
    try:
        cur = con.cursor()
        sql = """
            INSERT INTO events (ts, type, uid, value)
            VALUES (NOW(), %s, %s, %s)
        """
        cur.execute(sql, (
            p.get("type"),
            p.get("uid"),
            p.get("value"),
        ))
        con.commit()
    finally:
        con.close()

def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[mqtttodb] connected rc={reason_code}")
    for t, q in TOPICS:
        client.subscribe(t, qos=q)
        print(f"[mqtttodb] subscribed {t}")

def on_message(client, userdata, msg):
    try:
        text = msg.payload.decode("utf-8", errors="replace").strip()
        payload = json.loads(text)
    except Exception:
        return

    try:
        if msg.topic == TOPIC_TELE:
            insert_telemetry_v2(payload)
        elif msg.topic == TOPIC_EVT:
            insert_event(payload)
    except Exception as e:
        print(f"[mqtttodb] DB insert error: {repr(e)}", file=sys.stderr)

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, KEEPALIVE)

    print("[mqtttodb] running (Ctrl+C to stop)")
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
