# host_telemetry.py
# Sends HOST,CPU:<fraction> lines to Arduino over serial at 115200 baud.
# Edit PORT to your Arduino's COM port (e.g., "COM4").

import time
import sys
import psutil
import serial

PORT = "COM5"    # <<--- CHANGE THIS to your Arduino COM port
BAUD = 115200
INTERVAL = 0.5   # seconds between sends

def main():
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except Exception as e:
        print("Error opening serial port:", e)
        sys.exit(1)
    print("Connected to", PORT)
    try:
        while True:
            # psutil.cpu_percent(None) returns a float percent since last call
            cpu_pct = psutil.cpu_percent(interval=None)
            frac = cpu_pct / 100.0
            msg = f"HOST,CPU:{frac:.3f}\n"
            ser.write(msg.encode('utf-8'))
            print("SENT", msg.strip())
            time.sleep(INTERVAL)
    except KeyboardInterrupt:
        print("\nStopped by user")
        ser.close()

if __name__ == "__main__":
    main()
