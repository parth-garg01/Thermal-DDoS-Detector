/*
  thermal_dos_full_fusion_sustained.ino
  Thermal DoS Detector + EMA smoothing, slope (°C/s), sustained trigger, TEST/RESET commands.
  If SUSPECT persists >= SUSPECT_HOLD_MS, escalate to ATTACK.

  Hardware:
    LM35 -> A0
    Relay -> D8  (module recommended)
    I2C 16x2 LCD -> SDA=A4, SCL=A5 (address 0x27 default)

  Host telemetry:
    - Existing host_telemetry.py that sends: HOST,CPU:0.732
*/

#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <math.h>

// -------- Pins --------
const int LM35_PIN  = A0;
const int RELAY_PIN = 8;

// -------- ADC / Sensor --------
const float VREF   = 5.0;   // UNO default 5V reference
const int   ADC_MAX = 1023; // 10-bit

// -------- Timings --------
const unsigned long SAMPLE_MS  = 250;   // sensor sample interval (ms)
const unsigned long DISPLAY_MS = 1000;  // LCD/serial display rate (ms)

unsigned long SUSPECT_HOLD_MS  = 8000;  // sustained condition time (ms)
unsigned long COOLDOWN_HOLD_MS = 5000;  // cooldown hold time (ms)

// -------- Tuned thresholds (configure these) --------
float BASE_TEMP       = 0.0;   // learned at boot
float TEMP_MARGIN     = 8.0;   // above baseline -> SUSPECT (°C)
float TEMP_ATTACK     = 10.0;  // above baseline -> ATTACK (°C) (unused for unconditional escalation)
const float SLOPE_HIGH_CPS = 0.20;  // slope threshold °C/s

float TEMP_COOL_DELTA = 5.0;
const float EMA_ALPHA      = 0.25;  // 0..1 smoothing for EMA

// -------- Host telemetry influence (optional) --------
float hostCPU = 0.0;                // 0.0 .. 1.0
const float HOST_BUSY_THRESHOLD = 0.75; // consider host busy if >= 0.75

// -------- Minimal host-steady fusion window (still collected, not required) --------
const int WIN_SAMPLES = 32;      // ~8s window @ 250ms per sample
float hostWindow[WIN_SAMPLES];
int   winIdx = 0;
int   winCount = 0;

// thresholds for deciding steady host (kept for debugging/optional use)
const float REQ_AVG_HOST = 0.85;  // require average CPU >= 85%
const float REQ_STD_HOST = 0.20;  // require low stddev (steady load)

// -------- FSM --------
enum State { LEARN, NORMAL, SUSPECT, ATTACK, COOLDOWN };
State fsm = LEARN;

// -------- Runtime vars --------
LiquidCrystal_I2C lcd(0x27,16,2);
float rawTempC = 0.0;
float emaTempC = 0.0;
float lastEma  = 0.0;
float slopeCps = 0.0;

unsigned long tState   = 0;
unsigned long tSample  = 0;
unsigned long tDisplay = 0;
unsigned long sustainMs= 0;

void relayOn(bool on) { digitalWrite(RELAY_PIN, on ? HIGH : LOW); }

// --- Sensor read (single sample) ---
float readTempC_once() {
  int adc = analogRead(LM35_PIN);
  float v = ((float)adc * (VREF / (float)ADC_MAX));
  return (v / 0.010); // 10 mV/°C -> °C
}

// --- Small statistics helpers ---
float meanArr(float *arr, int n) {
  if (n <= 0) return 0.0;
  float s = 0.0;
  for (int i=0;i<n;i++) s += arr[i];
  return s / n;
}

float stddevArr(float *arr, int n, float meanVal) {
  if (n <= 1) return 0.0;
  float s = 0.0;
  for (int i=0;i<n;i++) {
    float d = arr[i] - meanVal;
    s += d * d;
  }
  return sqrt(s / (n - 1));
}

// --- Commands over Serial & HOST parsing ---
// TEST    -> force ATTACK immediately
// RESET   -> go to NORMAL, turn relay off
// BASE?   -> print baseline value
// BASE=xx -> set baseline to xx °C
// HOST,CPU:0.732 -> update hostCPU
void handleSerial() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  if (cmd.length() == 0) return;

  if (cmd.equalsIgnoreCase("TEST")) {
    Serial.println("CMD TEST -> forcing ATTACK");
    fsm = ATTACK; tState = millis();
    relayOn(true);
    return;
  } else if (cmd.equalsIgnoreCase("RESET")) {
    Serial.println("CMD RESET -> NORMAL");
    relayOn(false);
    fsm = NORMAL; tState = millis();
    return;
  } else if (cmd.equalsIgnoreCase("BASE?")) {
    Serial.print("BASE_TEMP="); Serial.println(BASE_TEMP,1);
    return;
  } else if (cmd.startsWith("BASE=")) {
    float v = cmd.substring(5).toFloat();
    if (v > -50 && v < 150) {
      BASE_TEMP = v;
      Serial.print("BASE set to "); Serial.println(BASE_TEMP,1);
    }
    return;
  }

  // Parse HOST telemetry lines e.g. "HOST,CPU:0.732"
  if (cmd.startsWith("HOST,")) {
    int idx = cmd.indexOf("CPU:");
    if (idx >= 0) {
      String num = cmd.substring(idx + 4);
      float v = num.toFloat();
      if (v >= 0.0 && v <= 1.0) {
        hostCPU = v;
        Serial.print("HOST CPU=");
        Serial.println(hostCPU,3);
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(RELAY_PIN, OUTPUT);
  relayOn(false);

  lcd.init(); lcd.backlight(); lcd.clear();
  lcd.setCursor(0,0); lcd.print("ThermalDoS Init");
  lcd.setCursor(0,1); lcd.print("Learning base...");

  // Quick baseline learn (~5s)
  Serial.println("Learning baseline temperature (5 s)");
  float sum = 0.0; int n = 0;
  unsigned long t0 = millis();
  while (millis() - t0 < 5000UL) {
    float s = readTempC_once();
    sum += s; n++;
    delay(200);
  }
  BASE_TEMP = sum / max(n,1);
  Serial.print("Baseline Temp = "); Serial.println(BASE_TEMP,1);

  lcd.clear();
  lcd.print("Base="); lcd.print(BASE_TEMP,1); lcd.print("C");
  delay(900); lcd.clear();

  // Initialize EMA with first fresh read
  emaTempC = readTempC_once();
  lastEma  = emaTempC;

  fsm = NORMAL;
  tState = tSample = tDisplay = millis();
}

void loop() {
  handleSerial();

  unsigned long now = millis();

  // Sampling block (every SAMPLE_MS)
  if (now - tSample >= SAMPLE_MS) {
    tSample = now;

    // Read & smooth
    rawTempC = readTempC_once();
    emaTempC = EMA_ALPHA * rawTempC + (1.0 - EMA_ALPHA) * emaTempC;

    // Slope in °C/s using EMA
    float dT = emaTempC - lastEma;
    float dt = (float)SAMPLE_MS / 1000.0;
    slopeCps = dT / (dt > 0.0 ? dt : 1.0);
    lastEma = emaTempC;

    // ---- push hostCPU into small circular buffer ----
    hostWindow[winIdx] = hostCPU;
    winIdx = (winIdx + 1) % WIN_SAMPLES;
    if (winCount < WIN_SAMPLES) winCount++;

    // --- FSM ---
    switch (fsm) {
      case NORMAL: {
        bool hotDelta = (emaTempC - BASE_TEMP) > TEMP_MARGIN;
        bool hotSlope = slopeCps >= SLOPE_HIGH_CPS;
        bool hostBusy  = hostCPU >= HOST_BUSY_THRESHOLD;
        // hostBusy helps enter SUSPECT but ATTACK will happen if SUSPECT sustains >= SUSPECT_HOLD_MS
        if (hotDelta || hotSlope || hostBusy) {
          fsm = SUSPECT; tState = now; sustainMs = 0;
          Serial.println("-> SUSPECT");
        }
      } break;

      case SUSPECT: {
        bool condTempOrSlope = ((emaTempC - BASE_TEMP) > TEMP_MARGIN) || (slopeCps >= SLOPE_HIGH_CPS);
        bool condHost = hostCPU >= HOST_BUSY_THRESHOLD;
        if (condTempOrSlope || condHost) {
          sustainMs += SAMPLE_MS;

          // NEW: unconditional escalation — if SUSPECT persists long enough, go to ATTACK
          if (sustainMs >= SUSPECT_HOLD_MS) {
            fsm = ATTACK; tState = now;
            relayOn(true);
            Serial.println("-> ATTACK (sustained SUSPECT)");
          }
        } else {
          // clear accumulators and go back to NORMAL
          sustainMs = 0;
          winIdx = 0; winCount = 0;
          fsm = NORMAL; tState = now;
          Serial.println("-> NORMAL (not sustained)");
        }
      } break;

      case ATTACK: {
        // Stay until cooled relative to baseline
        if ((emaTempC - BASE_TEMP) < TEMP_COOL_DELTA) {
          fsm = COOLDOWN; tState = now;
          Serial.println("-> COOLDOWN");
        }
      } break;

      case COOLDOWN: {
        if (now - tState > COOLDOWN_HOLD_MS) {
          relayOn(false);
          fsm = NORMAL; tState = now;
          Serial.println("-> NORMAL (recovered)");
        }
      } break;

      case LEARN:
        // not used after setup
        break;
    }
  }

  // Display/print block (every DISPLAY_MS)
  if (now - tDisplay >= DISPLAY_MS) {
    tDisplay = now;

    // Serial CSV-ish line (easy to capture)
    Serial.print("TempRaw=");  Serial.print(rawTempC,1);
    Serial.print(",TempEMA="); Serial.print(emaTempC,1);
    Serial.print(",dT/s=");    Serial.print(slopeCps,3);
    Serial.print(",State=");
    switch (fsm) {
      case NORMAL:   Serial.print("NORMAL"); break;
      case SUSPECT:  Serial.print("SUSPECT"); break;
      case ATTACK:   Serial.print("ATTACK"); break;
      case COOLDOWN: Serial.print("COOLDOWN"); break;
      default:       Serial.print("LEARN"); break;
    }
    Serial.print(",Base="); Serial.println(BASE_TEMP,1);

    // Machine-friendly DATA line
    Serial.print("DATA,");
    Serial.print(millis());            // ms since boot
    Serial.print(",");
    Serial.print(emaTempC,2);          // temperature EMA
    Serial.print(",");
    Serial.print(slopeCps,3);          // slope °C/s
    Serial.print(",");
    Serial.println(hostCPU,3);

    // LCD display
    lcd.clear();
    lcd.setCursor(0,0);
    lcd.print("T:"); lcd.print(emaTempC,1); lcd.print("C ");
    lcd.print("S:"); lcd.print(slopeCps,2);
    lcd.setCursor(0,1);
    if      (fsm==NORMAL)   lcd.print("NORMAL   ");
    else if (fsm==SUSPECT)  lcd.print("SUSPECT  ");
    else if (fsm==ATTACK)   lcd.print("ATTACK   ");
    else if (fsm==COOLDOWN) lcd.print("COOLDOWN ");
    lcd.print(" dB:");
    lcd.print(emaTempC - BASE_TEMP,1); // delta from base
  }
}
