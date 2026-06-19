#include <SPI.h>
#include <Wire.h>
#include "HX711.h"
#include <Adafruit_GFX.h>
#include <Adafruit_ILI9341.h>

// ================= TFT Display =================
#define TFT_CS 8
#define TFT_DC 9
#define TFT_RST 10
Adafruit_ILI9341 tft = Adafruit_ILI9341(TFT_CS, TFT_DC, TFT_RST);

// ================= HX711 (Load Cell) =================
const int LOADCELL_DOUT_PIN = 2;
const int LOADCELL_SCK_PIN = 3;
HX711 scale;
float calibration_factor = 36.059;
float offset_kg = 0.0;

// ================= Sensors =================
const int BPMPotPin = A0;
const int tempPin = A1;
const int spo2Pin = A3;
const int trigPin = 4;
const int echoPin = 5;

// ================= Control Pins =================
const int startPin = 7;    // D7 - Parameters Screen
const int analysisPin = 6; // D6 - Analysis Screen
const int diagnosisPin = 12; // D12 - Diagnosis Screen

// ================= Variables =================
float cm;
int respirationRate = 16;
int myBPM = 0;
bool scaleInitialized = false;
unsigned long lastUpdate = 0;
int currentScreen = 0; // 0=welcome, 1=parameters, 2=analysis, 3=diagnosis

// ================= Health States Enum =================
enum HealthState { LOW_STATE = 0, NORMAL_STATE = 1, HIGH_STATE = 2 };

// ================================================================
// ------------------- Optimized Diagnosis System -----------------
// ================================================================

HealthState getBMIState(float bmi) {
  if (bmi < 18.5) return LOW_STATE;
  if (bmi <= 24.9) return NORMAL_STATE;
  return HIGH_STATE;
}

HealthState getBPMState(int bpm) {
  if (bpm < 60) return LOW_STATE;
  if (bpm <= 100) return NORMAL_STATE;
  return HIGH_STATE;
}

HealthState getTempState(float tempC) {
  if (tempC < 36.0) return LOW_STATE;
  if (tempC <= 37.2) return NORMAL_STATE;
  return HIGH_STATE;
}

HealthState getSPO2State(int spo2) {
  if (spo2 < 95) return LOW_STATE;
  if (spo2 <= 98) return NORMAL_STATE;
  return HIGH_STATE;
}


HealthState getRespirationState(int respiration) {
  if (respiration < 12) return LOW_STATE;
  if (respiration <= 20) return NORMAL_STATE;
  return HIGH_STATE;
}

int generateCaseID(HealthState bmi, HealthState bpm, HealthState temp, HealthState spo2, HealthState resp) {
  return bmi * 81 + bpm * 27 + temp * 9 + spo2 * 3 + resp;
}

// Shortened strings to save memory
const char* getHealthRemark(int caseID) {
  switch(caseID) {
    case 3: return "Underweight, low O2";
    case 7: return "Fast breathing, low O2";
    case 9: return "Weak metabolism";
    case 13: return "Low O2, mild stress";
    case 15: return "Fever + low O2";
    case 18: return "High HR, low O2";
    case 22: return "Fast HR + low O2";
    case 31: return "Stable, low O2";
    case 37: return "Mild low O2";
    case 40: return "Low oxygen only";
    case 242: return "All vitals elevated"; // ADDED: All HIGH case
    default: return "Abnormal pattern";
  }
}

const char* getPredictedDisease(int caseID) {
  switch(caseID) {
    case 3: return "Malnutrition";
    case 7: return "COPD/Asthma";
    case 9: return "Low thyroid";
    case 13: return "Anemia";
    case 15: return "Infection";
    case 18: return "Shock/Anemia";
    case 22: return "Hypoxia";
    case 31: return "Lung issue";
    case 37: return "Mild anemia";
    case 40: return "Mild COPD";
    case 242: return "Sepsis/Systemic infection"; // ADDED: All HIGH case
    default: return "Needs checkup";
  }
}

const char* getRecommendations(int caseID) {
  switch(caseID) {
    case 3: return "Nutrition & iron";
    case 7: return "Inhalers & tests";
    case 9: return "Thyroid tests";
    case 13: return "Diet & supplements";
    case 15: return "Antibiotics & rest";
    case 18: return "Emergency care";
    case 22: return "ECG & lung tests";
    case 31: return "Oxygen therapy";
    case 37: return "Iron & diet change";
    case 40: return "Stop smoking & rehab";
    case 242: return "Emergency hospitalization"; // ADDED: All HIGH case
    default: return "See doctor";
  }
}

void showDiagnosis(float BMI, int BPM, float tempC, int spo2, int respiration) {
    tft.fillScreen(ILI9341_BLACK);
    tft.fillRect(0, 0, 320, 30, ILI9341_RED);

    tft.setTextColor(ILI9341_WHITE);
    tft.setTextSize(2);
    tft.setCursor(80, 8);
    tft.println("DIAGNOSIS");

    HealthState bmiState = getBMIState(BMI);
    HealthState bpmState = getBPMState(BPM);
    HealthState tempState = getTempState(tempC);
    HealthState spo2State = getSPO2State(spo2);
    HealthState respState = getRespirationState(respiration);
    int caseID = generateCaseID(bmiState, bpmState, tempState, spo2State, respState);

    tft.setTextSize(1);
    tft.setTextColor(ILI9341_YELLOW);
    tft.setCursor(10, 40);
    tft.print("Case: "); tft.println(caseID);

    tft.setTextColor(ILI9341_CYAN);
    tft.setCursor(10, 55);
    tft.println("Remark:");
    tft.setTextColor(ILI9341_WHITE);
    tft.setCursor(10, 65);
    tft.println(getHealthRemark(caseID));

    tft.setTextColor(ILI9341_CYAN);
    tft.setCursor(10, 85);
    tft.println("Condition:");
    tft.setTextColor(ILI9341_WHITE);
    tft.setCursor(10, 95);
    tft.println(getPredictedDisease(caseID));

    tft.setTextColor(ILI9341_CYAN);
    tft.setCursor(10, 115);
    tft.println("Advice:");
    tft.setTextColor(ILI9341_GREEN);
    tft.setCursor(10, 125);
    tft.println(getRecommendations(caseID));

    tft.setTextColor(ILI9341_CYAN);
    tft.setTextSize(1);
    tft.setCursor(40, 220);
    tft.println("D12 OFF to go back");
}

// ================================================================
// ------------------- Display Functions -------------------------
// ================================================================
void showWelcomeScreen() {
    tft.fillScreen(ILI9341_BLACK);

    tft.setTextColor(ILI9341_CYAN);
    tft.setTextSize(3);
    tft.setCursor(25, 40);
    tft.println("WELCOME TO CST");

    tft.setTextColor(ILI9341_YELLOW);
    tft.setTextSize(2);
    tft.setCursor(15, 80);
    tft.println("Health Monitor");

    tft.setTextColor(ILI9341_GREEN);
    tft.setTextSize(2);
    tft.setCursor(40, 130);
    tft.println("Developed by");

    tft.setTextColor(ILI9341_MAGENTA);
    tft.setCursor(80, 160);
    tft.println("GROUP 3");

    tft.setTextColor(ILI9341_CYAN);
    tft.setTextSize(1);
    tft.setCursor(25, 220);
    tft.println("D7: Parameters");
}

void displayParameters(float BMI, int BPM, float tempC, int spo2, int respiration) {
    tft.fillScreen(ILI9341_BLACK);
    tft.fillRect(0, 0, 320, 30, ILI9341_BLUE);

    tft.setTextColor(ILI9341_WHITE);
    tft.setTextSize(2);
    tft.setCursor(55, 8);
    tft.println("PARAMETERS");

    int y = 50;
    tft.setTextColor(ILI9341_YELLOW);
    tft.setTextSize(2);

    tft.setCursor(10, y);
    tft.print("BMI: "); tft.print(BMI, 1);
    tft.println(BMI < 18.5 ? " Low" : BMI <= 24.9 ? " Normal" : " High");
    y += 30;

    tft.setCursor(10, y);
    tft.print("Pulse: "); tft.print(BPM);
    tft.println(BPM < 60 ? " Low" : BPM > 100 ? " High" : " Normal");
    y += 30;

    tft.setCursor(10, y);
    tft.print("Temp: "); tft.print(tempC, 1);
    tft.println(tempC < 36.0 ? " Low" : tempC > 37.2 ? " High" : " Normal");
    y += 30;

    tft.setCursor(10, y);
    tft.print("SpO2: "); tft.print(spo2);
    tft.println(spo2 < 95 ? " Low" : " Normal");
    y += 30;

    tft.setCursor(10, y);
    tft.print("Resp: "); tft.print(respiration);
    tft.println(respiration < 12 ? " Low" : respiration > 20 ? " High" : " Normal");

    tft.setTextColor(ILI9341_CYAN);
    tft.setTextSize(1);
    tft.setCursor(20, 220);
    tft.println("D6: Analysis | All OFF: Home");
}

void showAnalysis(float BMI, int BPM, float tempC, int spo2, int respiration) {
    tft.fillScreen(ILI9341_BLACK);
    tft.fillRect(0, 0, 320, 30, ILI9341_DARKCYAN);

    tft.setTextColor(ILI9341_WHITE);
    tft.setTextSize(2);
    tft.setCursor(100, 8);
    tft.println("ANALYSIS");

    tft.setTextSize(2);
    tft.setTextColor(ILI9341_GREEN);

    int y = 60;

    tft.setCursor(10, y);
    tft.println(BMI < 18.5 ? "BMI: Underweight" : BMI <= 24.9 ? "BMI: Normal" : "BMI: Overweight");
    y += 30;

    tft.setCursor(10, y);
    tft.println(BPM < 60 ? "Pulse: Slow" : BPM > 100 ? "Pulse: Fast" : "Pulse: Normal");
    y += 30;

    tft.setCursor(10, y);
    tft.println(tempC > 37.2 ? "Temp: Fever" : tempC < 36.0 ? "Temp: Low" : "Temp: Normal");
    y += 30;

    tft.setCursor(10, y);
    tft.println(spo2 < 95 ? "SpO2: Low O2" : "SpO2: Normal");
    y += 30;

    tft.setCursor(10, y);
    tft.println(respiration < 12 ? "Resp: Slow" : respiration > 20 ? "Resp: Fast" : "Resp: Normal");

    tft.setTextColor(ILI9341_CYAN);
    tft.setTextSize(1);
    tft.setCursor(40, 220);
    tft.println("D12: Diagnosis | D6 OFF: Parameters | All OFF: Home");
}

// ================================================================
// ------------------------ Setup --------------------------------
// ================================================================
void setup() {
    Serial.begin(9600);

    scale.begin(LOADCELL_DOUT_PIN, LOADCELL_SCK_PIN);

    pinMode(trigPin, OUTPUT);
    pinMode(echoPin, INPUT);
    pinMode(startPin, INPUT);
    pinMode(analysisPin, INPUT);
    pinMode(diagnosisPin, INPUT);

    tft.begin();
    tft.setRotation(1);

    showWelcomeScreen();

    Serial.println("System Ready...");
}

// ================================================================
// ------------------------ Loop ---------------------------------
// ================================================================
void loop() {
    int D7State = digitalRead(startPin);
    int D6State = digitalRead(analysisPin);
    int D12State = digitalRead(diagnosisPin);

    if (!scaleInitialized) {
        scale.set_scale(calibration_factor);
        scaleInitialized = true;
    }

    // Read sensors
    float tempC = (analogRead(tempPin) * 5.0 / 1023.0) * 100.0;

    digitalWrite(trigPin, LOW);
    delayMicroseconds(2);
    digitalWrite(trigPin, HIGH);
    delayMicroseconds(10);
    digitalWrite(trigPin, LOW);
    long duration = pulseIn(echoPin, HIGH);
    cm = duration * 0.034 / 2;
    float virtualHeight = constrain((cm - 4.4) * (200.0 / (1106.3 - 4.4)), 0, 200);

    float weight = scale.get_units(5) / 1000.0;
    float heightMeters = virtualHeight / 100.0;
    float BMI = (heightMeters > 0) ? weight / (heightMeters * heightMeters) : 0;

    int spo2 = map(analogRead(spo2Pin), 0, 1023, 90, 100);
    int analogValue = analogRead(BPMPotPin);
    myBPM = map(analogValue, 0, 1023, 40, 170);
    respirationRate = map(analogValue, 0, 1023, 10, 25);

    if (millis() - lastUpdate > 1000) {
        Serial.print("Temp: "); Serial.print(tempC, 1);
        Serial.print(" | W: "); Serial.print(weight, 2);
        Serial.print(" | H: "); Serial.print(virtualHeight, 1);
        Serial.print(" | BMI: "); Serial.print(BMI, 1);
        Serial.print(" | SpO2: "); Serial.print(spo2);
        Serial.print(" | BPM: "); Serial.print(myBPM);
        Serial.print(" | Resp: "); Serial.println(respirationRate);

        // Debug: Show states and case ID
        HealthState bmiState = getBMIState(BMI);
        HealthState bpmState = getBPMState(myBPM);
        HealthState tempState = getTempState(tempC);
        HealthState spo2State = getSPO2State(spo2);
        HealthState respState = getRespirationState(respirationRate);
        int caseID = generateCaseID(bmiState, bpmState, tempState, spo2State, respState);
        Serial.print("States: BMI="); Serial.print(bmiState);
        Serial.print(" BPM="); Serial.print(bpmState);
        Serial.print(" Temp="); Serial.print(tempState);
        Serial.print(" SpO2="); Serial.print(spo2State);
        Serial.print(" Resp="); Serial.print(respState);
        Serial.print(" | Case ID: "); Serial.println(caseID);

        lastUpdate = millis();
    }

    // Screen control logic
    if (D7State == LOW && D6State == LOW && D12State == LOW) {
        // All OFF - Welcome screen
        if (currentScreen != 0) {
            showWelcomeScreen();
            currentScreen = 0;
        }
    }
    else if (D7State == HIGH && D6State == LOW && D12State == LOW) {
        // D7 HIGH only - Parameters screen
        if (currentScreen != 1) {
            displayParameters(BMI, myBPM, tempC, spo2, respirationRate);
            currentScreen = 1;
        }
    }
    else if (D7State == HIGH && D6State == HIGH && D12State == LOW) {
        // D7 & D6 HIGH - Analysis screen
        if (currentScreen != 2) {
            showAnalysis(BMI, myBPM, tempC, spo2, respirationRate);
            currentScreen = 2;
        }
    }
    else if (D7State == HIGH && D6State == HIGH && D12State == HIGH) {
        // All HIGH - Diagnosis screen (ALWAYS SHOW)
        if (currentScreen != 3) {
            showDiagnosis(BMI, myBPM, tempC, spo2, respirationRate);
            currentScreen = 3;
        }
    }
    else if (currentScreen == 3 && D12State == LOW) {
        // From Diagnosis back to Analysis (D12 OFF)
        if (D7State == HIGH && D6State == HIGH) {
            showAnalysis(BMI, myBPM, tempC, spo2, respirationRate);
            currentScreen = 2;
        }
    }
    else if (currentScreen == 2 && D6State == LOW && D12State == LOW) {
        // From Analysis back to Parameters (D6 OFF, D12 OFF)
        if (D7State == HIGH) {
            displayParameters(BMI, myBPM, tempC, spo2, respirationRate);
            currentScreen = 1;
        }
    }

    delay(200);
}
