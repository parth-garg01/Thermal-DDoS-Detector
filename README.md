# Thermal DDoS Detector

A hardware-based security monitoring system that detects Denial of Service (DoS) attacks by monitoring temperature and CPU usage patterns using Arduino and real-time data fusion.

## 📋 Overview

This project implements a thermal-based DoS detection system that correlates CPU temperature changes with host CPU usage to identify potential DoS attacks. When abnormal patterns are detected, the system automatically triggers a relay to cut power and protect the system.

### Key Features

- **Real-time Temperature Monitoring** - Continuous monitoring using LM35 temperature sensor
- **EMA Smoothing** - Exponential Moving Average for noise reduction
- **Multi-factor Detection** - Combines temperature delta, rate of change, and CPU usage
- **Sustained Attack Detection** - Requires conditions to persist for 8 seconds before triggering
- **Auto-recovery** - Automatic cooldown and system recovery
- **Live Visualization** - Real-time plotting of metrics and correlation analysis
- **LCD Display** - 16x2 I2C display shows current status
- **Serial Commands** - Remote control via serial interface

## 🔧 Hardware Requirements

### Components

| Component | Specification | Purpose |
|-----------|--------------|---------|
| Arduino Uno/Nano | ATmega328P | Main controller |
| LM35 Temperature Sensor | ±0.5°C accuracy | Temperature monitoring |
| Relay Module | 5V, active HIGH | Power cutoff control |
| I2C LCD Display | 16x2, address 0x27 | Status display |
| Jumper Wires | - | Connections |

### Pin Connections

```
LM35 Temperature Sensor:
  - VCC  → 5V
  - OUT  → A0
  - GND  → GND

Relay Module:
  - VCC  → 5V
  - IN   → D8
  - GND  → GND

I2C LCD Display (16x2):
  - VCC  → 5V
  - GND  → GND
  - SDA  → A4
  - SCL  → A5
```

## 💻 Software Requirements

### Arduino

- Arduino IDE 1.8.x or higher
- **Libraries Required:**
  - `Wire.h` (built-in)
  - `LiquidCrystal_I2C.h` - [Install from Library Manager](https://github.com/johnrickman/LiquidCrystal_I2C)

### Python (for Host Telemetry & Visualization)

- Python 3.7 or higher
- **Required Packages:**
  ```bash
  pip install psutil pyserial matplotlib numpy
  ```

## 🚀 Installation

### 1. Arduino Setup

1. Open Arduino IDE
2. Install the `LiquidCrystal_I2C` library:
   - Go to **Sketch** → **Include Library** → **Manage Libraries**
   - Search for "LiquidCrystal I2C"
   - Install the library by Frank de Brabander or Marco Schwartz

3. Open `final_code/final_code.ino`
4. **Configure settings** (if needed):
   ```cpp
   const int LM35_PIN  = A0;        // Temperature sensor pin
   const int RELAY_PIN = 8;         // Relay control pin
   unsigned long SUSPECT_HOLD_MS  = 8000;  // Sustained detection time
   unsigned long COOLDOWN_HOLD_MS = 5000;  // Recovery time
   ```

5. Upload to your Arduino board

### 2. Python Setup

1. Install Python dependencies:
   ```bash
   pip install psutil pyserial matplotlib numpy
   ```

2. **Configure COM Port** in Python scripts:
   - Edit `Thermal_ddos final/host_telemetry.py`
   - Edit `Thermal_ddos final/real_time_fusion.py`
   - Change `PORT = "COM5"` to your Arduino's COM port

   **Find your COM port:**
   - Windows: Check Device Manager → Ports (COM & LPT)
   - Linux/Mac: Usually `/dev/ttyUSB0` or `/dev/ttyACM0`

## 📖 Usage

### Basic Mode (Arduino Only)

1. Upload `final_code.ino` to Arduino
2. Open Serial Monitor (115200 baud)
3. System will:
   - Learn baseline temperature (5 seconds)
   - Display status on LCD
   - Print telemetry to Serial Monitor

**Serial Output Format:**
```
TempRaw=28.5,TempEMA=28.3,dT/s=0.045,State=NORMAL,Base=27.8
DATA,12450,28.30,0.045,0.000
```

### Advanced Mode (with Host Telemetry)

1. Upload Arduino code
2. Run host telemetry script:
   ```bash
   python "Thermal_ddos final/host_telemetry.py"
   ```
3. Script sends CPU usage to Arduino every 0.5 seconds

### Full Fusion Mode (with Live Visualization)

1. Upload Arduino code
2. Run real-time fusion script:
   ```bash
   python "Thermal_ddos final/real_time_fusion.py"
   ```
3. View live plots showing:
   - Temperature vs Host CPU correlation
   - Fusion score calculation
   - Attack detection visualization

## 🎯 Detection Algorithm

### State Machine

```
LEARN → NORMAL → SUSPECT → ATTACK → COOLDOWN → NORMAL
```

| State | Description | Trigger |
|-------|-------------|---------|
| **LEARN** | Initial 5-second baseline calibration | Boot-up only |
| **NORMAL** | Normal operation monitoring | Default state |
| **SUSPECT** | Potential attack detected | Temp/Slope/CPU threshold exceeded |
| **ATTACK** | Confirmed attack, relay activated | SUSPECT sustained ≥8 seconds |
| **COOLDOWN** | Waiting for system recovery | Temperature drops below threshold |

### Detection Criteria

The system enters **SUSPECT** state when:
- **Temperature Delta** > `TEMP_MARGIN` (default: configurable)
- **OR** Temperature **Slope** ≥ 0.20°C/s
- **OR** Host CPU ≥ 75%

The system escalates to **ATTACK** when:
- SUSPECT conditions persist for ≥ 8 seconds (configurable)

### Fusion Score Calculation

```python
score = W_DELTA × (ΔTemp/Threshold) + W_SLOPE × (Slope/Threshold) + W_HOST × (CPU%)
```

Default weights:
- `W_DELTA = 0.45` (Temperature delta)
- `W_SLOPE = 0.25` (Rate of change)
- `W_HOST = 0.30` (Host CPU usage)

Attack flagged when: `score ≥ 0.80` AND `correlation ≥ 0.55`

## 🛠️ Serial Commands

Send commands via Serial Monitor (115200 baud):

| Command | Description |
|---------|-------------|
| `TEST` | Force immediate ATTACK state (for testing) |
| `RESET` | Return to NORMAL state, turn off relay |
| `BASE?` | Print current baseline temperature |
| `BASE=xx` | Set baseline to xx°C manually |

## 📊 Monitoring & Debugging

### LCD Display Format

```
Line 1: T:28.5C S:0.12
Line 2: NORMAL   dB:0.7
```

- **T** - Current temperature (EMA smoothed)
- **S** - Temperature slope (°C/s)
- **State** - Current FSM state
- **dB** - Delta from baseline

### Serial Telemetry

Two formats are output:
1. **Human-readable:**
   ```
   TempRaw=28.5,TempEMA=28.3,dT/s=0.045,State=NORMAL,Base=27.8
   ```

2. **Machine-readable (DATA line):**
   ```
   DATA,<timestamp_ms>,<temp>,<slope>,<host_cpu>
   ```

## 🔧 Configuration & Tuning

### Threshold Adjustments

Edit in `final_code.ino`:

```cpp
// Detection sensitivity
float TEMP_MARGIN     = 0.0;   // °C above baseline → SUSPECT
const float SLOPE_HIGH_CPS = 0.20;  // °C/s threshold

// Timing
unsigned long SUSPECT_HOLD_MS  = 8000;  // ms before ATTACK
unsigned long COOLDOWN_HOLD_MS = 5000;  // ms cooldown period

// Host CPU threshold
const float HOST_BUSY_THRESHOLD = 0.75; // 0.0 to 1.0
```

### EMA Smoothing

```cpp
const float EMA_ALPHA = 0.25;  // 0..1, higher = more responsive
```

## 🐛 Troubleshooting

### LCD Not Working
- Check I2C address (try 0x3F if 0x27 doesn't work)
- Verify SDA/SCL connections
- Run I2C scanner sketch to find address

### Temperature Reading Issues
- Verify LM35 connections (VCC to 5V, not 3.3V)
- Check if sensor is properly seated
- Use multimeter to test sensor output voltage

### Relay Not Triggering
- Verify relay module type (active HIGH/LOW)
- Check power supply to relay module
- Test relay with `TEST` command

### Python Script Can't Connect
- Verify COM port in script matches Arduino
- Close Serial Monitor before running Python
- Check baud rate is 115200 in both Arduino and Python

### False Positives
- Increase `SUSPECT_HOLD_MS` for longer confirmation time
- Adjust `TEMP_MARGIN` threshold higher
- Reduce `HOST_BUSY_THRESHOLD` sensitivity

## 📁 Project Structure

```
DSD Project/
├── final_code/
│   └── final_code.ino          # Main Arduino sketch
├── Thermal_ddos final/
│   ├── host_telemetry.py       # Basic CPU telemetry sender
│   ├── real_time_fusion.py     # Advanced visualization
│   └── sketch_nov7a/           # Alternate sketch version
├── README.md                    # This file
└── .gitignore
```

## 🧪 Testing

### Manual Testing

1. **Normal Operation Test:**
   - Let system stabilize in NORMAL state
   - Verify baseline temperature is reasonable

2. **Attack Simulation:**
   - Run CPU stress test (e.g., Prime95, stress-ng)
   - Monitor temperature rise
   - Verify SUSPECT → ATTACK transition

3. **Serial Command Test:**
   - Send `TEST` command → should trigger ATTACK
   - Send `RESET` command → should return to NORMAL

4. **Recovery Test:**
   - After attack detection, stop stress test
   - Verify cooldown and return to NORMAL

## 📝 License

This project is open-source and available for educational purposes.

## 👥 Authors

- Parth Garg

## 🙏 Acknowledgments

- LM35 datasheet and application notes
- Arduino community for libraries and examples
- Python data visualization community

## 📧 Contact

For questions or contributions, please open an issue on GitHub.

---

**⚠️ Safety Warning:** This system is designed for educational and research purposes. Always ensure proper electrical safety when working with relay modules and power systems.
