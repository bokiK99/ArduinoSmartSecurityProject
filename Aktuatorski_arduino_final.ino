#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <Servo.h>

const unsigned long BAUD = 57600;

const int PINVENT = 2;   // relay/fan
const int PINSERVO = 3;  // lock servo
const int PINBUZZ = 6;   // buzzer

const int SERVOUNLOCKDEG = 90;
const int SERVOLOCKDEG   = 0;

#define LCDADDR 0x27   // ako je LCD prazan probaj 0x3F
LiquidCrystal_I2C lcd(LCDADDR, 20, 4);
Servo s;

// -------- Serial line parser --------
const size_t MAXLINE = 80;
char buf[MAXLINE + 1];
size_t len = 0;
bool overflowed = false;

// -------- States --------
bool ventOn = false;
int servoPos = SERVOLOCKDEG;

bool fireAlarm = false;
bool intrusionAlarm = false;

// -------- Auth countdown --------
bool authActive = false;
unsigned long authStartMs = 0;
const unsigned long AUTHDURATIONMS = 30000;
int lastShownSec = -1;

void replyAck(const char* what) { Serial.print("ACK;"); Serial.println(what); }
void replyErr(const char* what) { Serial.print("ERR;"); Serial.println(what); }

String onoff(bool v) { return v ? "ON" : "OFF"; }

void applyOutputs() {
  digitalWrite(PINVENT, ventOn ? HIGH : LOW);
  digitalWrite(PINBUZZ, (fireAlarm || intrusionAlarm) ? HIGH : LOW);
  s.write(servoPos);
}

void lcdPrintRow(int row, const String& text) {
  lcd.setCursor(0, row);
  String t = text;
  if (t.length() > 20) t = t.substring(0, 20);
  lcd.print(t);
  for (int i = t.length(); i < 20; i++) lcd.print(" ");
}

void renderLCD(int remainS) {
  lcdPrintRow(0, "FIRE " + onoff(fireAlarm) + "  INTR " + onoff(intrusionAlarm));
  String lockState = (servoPos == SERVOUNLOCKDEG) ? "UNLOCK" : "LOCK";
  lcdPrintRow(1, "VENT " + onoff(ventOn) + "  " + lockState);
  lcdPrintRow(2, "BUZZ " + onoff(fireAlarm || intrusionAlarm));

  if (authActive) lcdPrintRow(3, "AUTH WAIT " + String(remainS) + "s");
  else if (fireAlarm) lcdPrintRow(3, "STATUS FIRE ALARM");
  else if (intrusionAlarm) lcdPrintRow(3, "STATUS INTRUSION");
  else lcdPrintRow(3, "STATUS NORMAL");
}

void startAuthWait30() {
  authActive = true;
  authStartMs = millis();
  lastShownSec = -1;
}

void stopAuthWait() {
  authActive = false;
  lastShownSec = -1;
}

void authTick() {
  if (!authActive) return;

  unsigned long elapsed = millis() - authStartMs;
  long remainMs = (long)AUTHDURATIONMS - (long)elapsed;

  if (remainMs <= 0) {
    authActive = false;
    intrusionAlarm = true;      // timeout => intrusion alarm ON
    applyOutputs();
    renderLCD(0);
    // opcionalno: event na serial (actuatord može kasnije proslijediti)
    Serial.println("EVT;AUTHTIMEOUT;INTRUSIONALARMON");
    return;
  }

  int remainS = (int)(remainMs / 1000);
  if (remainS != lastShownSec) {
    lastShownSec = remainS;
    renderLCD(remainS);
  }
}

void handleCmd(const char* cmd) {
  if (strcmp(cmd, "VENTON") == 0) { ventOn = true; applyOutputs(); replyAck("VENTON"); }
  else if (strcmp(cmd, "VENTOFF") == 0) { ventOn = false; applyOutputs(); replyAck("VENTOFF"); }

  else if (strcmp(cmd, "UNLOCK") == 0) { servoPos = SERVOUNLOCKDEG; applyOutputs(); replyAck("UNLOCK"); }
  else if (strcmp(cmd, "LOCK") == 0) { servoPos = SERVOLOCKDEG; applyOutputs(); replyAck("LOCK"); }

  else if (strcmp(cmd, "FIREALARMON") == 0) { fireAlarm = true; stopAuthWait(); applyOutputs(); replyAck("FIREALARMON"); }
  else if (strcmp(cmd, "FIREALARMOFF") == 0) { fireAlarm = false; applyOutputs(); replyAck("FIREALARMOFF"); }

  else if (strcmp(cmd, "INTRUSIONALARMON") == 0) { intrusionAlarm = true; stopAuthWait(); applyOutputs(); replyAck("INTRUSIONALARMON"); }
  else if (strcmp(cmd, "INTRUSIONALARMOFF") == 0) { intrusionAlarm = false; applyOutputs(); replyAck("INTRUSIONALARMOFF"); }

  else if (strcmp(cmd, "AUTHWAIT30") == 0) { startAuthWait30(); replyAck("AUTHWAIT30"); }
  else if (strcmp(cmd, "AUTHOK") == 0) { stopAuthWait(); intrusionAlarm = false; applyOutputs(); replyAck("AUTHOK"); }
  else if (strcmp(cmd, "AUTHFAIL") == 0) { stopAuthWait(); intrusionAlarm = true; applyOutputs(); replyAck("AUTHFAIL"); }

  else if (strcmp(cmd, "PING") == 0) { replyAck("PING"); }
  else { replyErr("UNKNOWN"); }

  if (!authActive) renderLCD(0);
}

void handleLine(const char* line) {
  if (strncmp(line, "CMD;", 4) != 0) { replyErr("BAD_PREFIX"); return; }
  handleCmd(line + 4);
}

void setup() {
  pinMode(PINVENT, OUTPUT);
  pinMode(PINBUZZ, OUTPUT);
  s.attach(PINSERVO);

  ventOn = false;
  servoPos = SERVOLOCKDEG;
  fireAlarm = false;
  intrusionAlarm = false;
  authActive = false;

  applyOutputs();

  Serial.begin(BAUD);
  Wire.begin();

  lcd.init();
  lcd.backlight();
  lcd.clear();
  renderLCD(0);

  delay(200);
  Serial.println("READY;ACTUATOR;UNO;LCD");
}

void loop() {
  authTick();

  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\r') continue;

    if (c == '\n') {
      if (!overflowed) {
        buf[len] = 0;
        handleLine(buf);
      } else {
        replyErr("LINE_OVERFLOW");
      }
      len = 0;
      overflowed = false;
      continue;
    }

    if (!overflowed) {
      if (len < MAXLINE) buf[len++] = c;
      else overflowed = true;
    }
  }
}
