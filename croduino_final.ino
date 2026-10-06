#include <ESP8266WiFi.h>
#include <PubSubClient.h>

// -------------------- PROMIJENI OVO --------------------
const char* WIFISSID = "Kib";
const char* WIFIPASS = "09121999";
const char* MQTTHOST = "192.168.1.2";
const uint16_t MQTTPORT = 1883;

const char* TOPICTELE = "iottelemetry";
const char* TOPICEVT  = "iotevents";
const char* MQTTCLIENTID = "nova2-uart-bridge";
// -------------------------------------------------------

const unsigned long UARTBAUD = 57600;

// Line buffer
const size_t MAXLINELEN = 220;
char lineBuf[MAXLINELEN + 1];
size_t lineLen = 0;
bool overflowed = false;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFISSID, WIFIPASS);
  while (WiFi.status() != WL_CONNECTED) delay(300);
}

void connectMQTT() {
  mqtt.setServer(MQTTHOST, MQTTPORT);
  while (!mqtt.connected()) {
    mqtt.connect(MQTTCLIENTID);
    delay(400);
  }
}

bool mqttPublish(const char* topic, const String& payload) {
  if (!mqtt.connected()) return false;
  return mqtt.publish(topic, payload.c_str(), false);
}

String trimCopy(String s) { s.trim(); return s; }

// ---------- Telemetry: "T;MQRAW:81;MQAVG:81;PIR:1;STATE:ALARM"
void handleTelemetry(const String& line) {
  int mqRaw = -1, mqAvg = -1, pir = -1;
  String state = "";

  int pos = 2; // after "T;"
  while (pos < (int)line.length()) {
    int next = line.indexOf(';', pos);
    String token = (next == -1) ? line.substring(pos) : line.substring(pos, next);

    int colon = token.indexOf(':');
    if (colon != -1) {
      String key = token.substring(0, colon);
      String val = token.substring(colon + 1);
      key.trim(); val.trim();

      if (key == "MQRAW") mqRaw = val.toInt();
      else if (key == "MQAVG") mqAvg = val.toInt();
      else if (key == "PIR") pir = val.toInt();
      else if (key == "STATE") state = val;
    }

    if (next == -1) break;
    pos = next + 1;
  }

  String json = "{";
  json += "\"mqraw\":" + String(mqRaw) + ",";
  json += "\"mqavg\":" + String(mqAvg) + ",";
  json += "\"pir\":" + String(pir) + ",";
  json += "\"state\":\"" + state + "\"";
  json += "}";

  mqttPublish(TOPICTELE, json);
}

// ---------- Events: "E;RFID_AUTH;UID:606B4F55"
bool extractUidFromTokens(const String& t2, const String& t3, String& uidOut) {
  uidOut = "";
  String tok = (t2.startsWith("UID:")) ? t2 : ((t3.startsWith("UID:")) ? t3 : "");
  if (tok.length() == 0) return false;
  uidOut = tok.substring(4);
  uidOut.trim();
  return uidOut.length() > 0;
}

void publishEventJson(const String& type, const String& uid) {
  String json = "{";
  json += "\"type\":\"" + type + "\"";
  if (uid.length() > 0) json += ",\"uid\":\"" + uid + "\"";
  json += "}";
  mqttPublish(TOPICEVT, json);
}

void handleEventCSV(const String& line) {
  // format: E;<EVENT>;<ARG1>;<ARG2>...
  // primjer: E;RFID_DEBUG;UID:606B4F55
  //         E;RFID_AUTH;UID:606B4F55
  //         E;RFID_UNAUTH;UID:FD24BD24
  //         E;ALARM_OFF_REQ;UID:606B4F55

  int p1 = line.indexOf(';');
  if (p1 == -1) return;
  int p2 = line.indexOf(';', p1 + 1);

  String ev = (p2 == -1) ? line.substring(p1 + 1) : line.substring(p1 + 1, p2);
  ev = trimCopy(ev);

  // Ignore debug completely
  if (ev == "RFID_DEBUG") return;

  // Grab up to two more tokens (UID usually sits here)
  String t2 = "", t3 = "";
  if (p2 != -1) {
    int p3 = line.indexOf(';', p2 + 1);
    t2 = (p3 == -1) ? line.substring(p2 + 1) : line.substring(p2 + 1, p3);
    t2 = trimCopy(t2);
    if (p3 != -1) {
      int p4 = line.indexOf(';', p3 + 1);
      t3 = (p4 == -1) ? line.substring(p3 + 1) : line.substring(p3 + 1, p4);
      t3 = trimCopy(t3);
    }
  }

  // Map event names to DB-friendly types
  String type = "";
  if (ev == "RFID_AUTH") type = "RFIDAUTH";
  else if (ev == "RFID_UNAUTH") type = "RFIDUNAUTH";
  else if (ev == "ALARM_OFF_REQ") type = "ALARMOFFREQ";
  else {
    return; // ignore unknown events
  }

  String uid = "";
  extractUidFromTokens(t2, t3, uid); // uid may stay empty (ok)
  publishEventJson(type, uid);
}

void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line.startsWith("T;")) handleTelemetry(line);
  else if (line.startsWith("E;")) handleEventCSV(line);
  else {
    // ignore
  }
}

void setup() {
  Serial.begin(UARTBAUD);
  delay(200);
  connectWiFi();
  connectMQTT();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqtt.connected()) connectMQTT();
  mqtt.loop();

  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;

    if (c == '\n') {
      if (!overflowed && lineLen > 0) {
        lineBuf[lineLen] = 0;
        handleLine(String(lineBuf));
      }
      lineLen = 0;
      overflowed = false;
      continue;
    }

    if (!overflowed) {
      if (lineLen < MAXLINELEN) lineBuf[lineLen++] = c;
      else overflowed = true;
    }
  }
}
