#!/usr/bin/env python3
import json
import MySQLdb as mdb

import tornado.ioloop
import tornado.web
import tornado.websocket

import paho.mqtt.client as mqtt

# ---------------- DB ----------------
DBHOST = "localhost"
DBUSER = "sensorwriter"
DBPASS = "password"
DBNAME = "sensors"

# ---------------- WS ----------------
HTTPPORT = 8888

# ---------------- MQTT ----------------
MQTTBROKER = "127.0.0.1"
MQTTPORT = 1883
MQTTKEEPALIVE = 60
TOPIC_CMD = "iotcmd"

def dbconnect():
    return mdb.connect(DBHOST, DBUSER, DBPASS, DBNAME)

def fetchlatest():
    con = dbconnect()
    try:
        cur = con.cursor(mdb.cursors.DictCursor)
        cur.execute("SELECT * FROM telemetry_v2 ORDER BY id DESC LIMIT 1")
        telemetry = cur.fetchone()
        cur.execute("SELECT * FROM events ORDER BY id DESC LIMIT 10")
        events = cur.fetchall()
        return telemetry, events
    finally:
        con.close()

# One global MQTT client (publish-only)
mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqttc.connect(MQTTBROKER, MQTTPORT, MQTTKEEPALIVE)
mqttc.loop_start()

def publish_cmd(cmd: str, src: str):
    payload = {"cmd": cmd, "src": src}
    mqttc.publish(TOPIC_CMD, json.dumps(payload), qos=0, retain=False)

class WsHandler(tornado.websocket.WebSocketHandler):
    clients = set()

    def check_origin(self, origin):
        return True

    def open(self):
        WsHandler.clients.add(self)
        self.write_message(json.dumps({"type": "status", "msg": "wsconnected"}))

    def on_close(self):
        WsHandler.clients.discard(self)

    def on_message(self, message):
        try:
            data = json.loads(message)
        except Exception:
            self.write_message(json.dumps({"type": "error", "msg": "badjson"}))
            return

        cmd = str(data.get("cmd", "")).strip().upper()

        allowed = {
            "VENTON", "VENTOFF",
            "UNLOCK", "LOCK",
            "FIREALARMON", "FIREALARMOFF",
            "INTRUSIONALARMON", "INTRUSIONALARMOFF",
            "AUTHWAIT30", "AUTHOK", "AUTHFAIL",
            "PING",
        }
        if cmd not in allowed:
            self.write_message(json.dumps({"type": "error", "msg": "unknowncmd", "cmd": cmd}))
            return

        # 1) log in DB
        con = dbconnect()
        try:
            cur = con.cursor()
            cur.execute(
                "INSERT INTO commands (ts, cmd, source, status) VALUES (NOW(), %s, %s, %s)",
                (cmd, "web", "queued")
            )
            con.commit()
        finally:
            con.close()

        # 2) publish to iotcmd (actuatord will execute on serial)
        publish_cmd(cmd, "web")

        # 3) ack back to browser
        self.write_message(json.dumps({"type": "ack", "cmd": cmd, "published": True}))

def pushupdate():
    telemetry, events = fetchlatest()
    msg = json.dumps({"type": "snapshot", "telemetry": telemetry, "events": events}, default=str)
    for c in list(WsHandler.clients):
        try:
            c.write_message(msg)
        except Exception:
            pass

def makeapp():
    return tornado.web.Application([
        (r"/ws", WsHandler),
    ])

if __name__ == "__main__":
    app = makeapp()
    app.listen(HTTPPORT, address="0.0.0.0")
    print(f"[wsscada] ws on :{HTTPPORT}/ws, publishing commands to {TOPIC_CMD}")
    tornado.ioloop.PeriodicCallback(pushupdate, 1000).start()
    tornado.ioloop.IOLoop.current().start()
