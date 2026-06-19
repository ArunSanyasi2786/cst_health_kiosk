# CST Health Monitoring Station

A production-style **PyQt6 kiosk application** for the **CST Final Year Project**, designed for a **1024x600 Raspberry Pi 4B touchscreen** and also usable on a **laptop for demo and development**.

This project is built as a **modular, maintainable, service-driven desktop kiosk** for health screening and reporting. It supports both:

- **Demo mode** for presentations, UI review, and offline showcasing
- **Hardware mode** for live sensor integration through **ESP32 / UART serial communication**

The application is designed with a **glossy futuristic blue medical UI**, structured around a **QStackedWidget navigation system**, reusable widgets, service-based logic, persistent settings, session storage, reporting, QR generation, and administrator tools.

---

## 1. Project Purpose

The CST Health Monitoring Station is intended to provide a guided kiosk workflow where a user can:

- start a health checkup
- choose between demo mode or hardware mode
- measure key health indicators
- view a summarized results dashboard
- open detailed explanations for each metric
- generate QR handoff / reports
- access consult guidance
- allow administrators to manage settings, calibration, thresholds, diagnosis logic, storage, and publishing

The system is structured so that **frontend screens, backend services, stored session data, and generated artifacts are all linked together** rather than existing as isolated pieces.

---

## 2. Core Design Principles

This project follows these design principles:

### 2.1 Modular Architecture
The app is split into:

- **core** for runtime foundations
- **services** for business logic and data handling
- **widgets** for reusable UI components
- **screens** for complete interface pages
- **data** for persistent files, database, reports, and generated outputs
- **assets** for images, icons, sounds, and fonts

### 2.2 Linked File Structure
Every important file should connect to the others through clear responsibilities. For example:

- `main.py` builds the application and wires services + screens together
- screens read from `app_state` and services
- services read/write `data/` and update session payloads
- detail screens depend on shared measurement payloads from results/session services
- admin screens depend on configuration, threshold, calibration, publish, and storage services
- assets are resolved centrally rather than hardcoded randomly across files

### 2.3 Resilience
The app is designed so that:

- missing assets do not immediately crash the app
- placeholder behavior exists while modules are still evolving
- demo mode keeps the UI functional even when hardware is unavailable
- screen constructors and service constructors are handled flexibly
- session payloads can come from multiple sources during development

### 2.4 Professional Kiosk Experience
The UI is intended to feel:

- premium
- futuristic
- medically themed
- touch-friendly
- presentation-ready
- readable on a 1024x600 screen

---

## 3. Main Features

### Public User Flow
- Welcome screen with brand identity and entry flow
- Mode selection for demo mode or hardware mode
- Measuring screen for live or simulated health acquisition
- Results screen showing all measured values
- QR screen for result-sharing workflow
- Consult screen for guidance and interpretation support

### Metric Detail Screens
- BMI detail screen
- Temperature detail screen
- SpO₂ detail screen
- Pulse detail screen
- Respiratory-rate detail screen

Each detail screen gives:
- the current value
- the category
- interpretation
- threshold band visualization
- recommendations / supportive guidance

### Administrator Flow
- Admin login
- Admin panel
- Settings screen
- Calibration screen
- Parameters screen
- Diagnosis screen
- Storage screen
- Publish screen

### Backend / Data Features
- SQLite-based storage
- JSON-backed settings and thresholds
- report generation
- QR generation
- export and publish workflows
- connection and serial services
- demo payload generation
- maintainable session handling

---

## 4. Target Metrics

The kiosk is built around the following health indicators:

- **Weight**
- **Height**
- **BMI**
- **Temperature**
- **SpO₂**
- **Pulse**
- **Respiratory Rate**

These are usually stored in a shared session payload under `measurements`, for example:

```json
{
  "session_id": "demo-session",
  "mode": "demo",
  "measurements": {
    "weight": 68.0,
    "height": 171.0,
    "bmi": 23.3,
    "temperature": 36.8,
    "spo2": 98,
    "pulse_rate": 76,
    "respiratory_rate": 16
  }
}