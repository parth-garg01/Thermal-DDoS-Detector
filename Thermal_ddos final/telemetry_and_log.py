# telemetry_and_log.py
# Sends HOST,CPU:<fraction> to Arduino AND logs everything Arduino prints to a CSV.
import time, sys, psutil, serial, threading, queue, os

PORT = "COM5"     # <- your Arduino port
BAUD = 115200
SEND_INTERVAL = 0.5  # seconds
ts = int(time.time())
CSV = f"log_{ts}.csv"

stop_flag = False
q = queue.Queue()

def sender(ser):
    global stop_flag
    while not stop_flag:
        cpu = psutil.cpu_percent(interval=None) / 100.0
        msg = f"HOST,CPU:{cpu:.3f}\n"
        try:
            ser.write(msg.encode("utf-8"))
        except Exception as e:
            print("Write error:", e)
            break
        # also queue a local note (not from Arduino) for CSV context
        q.put((time.time(), f"HOST_OUT,{cpu:.3f}"))
        time.sleep(SEND_INTERVAL)

def reader(ser):
    global stop_flag
    while not stop_flag:
        try:
            line = ser.readline().decode("utf-8", errors="replace").strip()
        except Exception as e:
            print("Read error:", e)
            break
        if line:
            q.put((time.time(), f"ARDUINO,{line}"))

def main():
    global stop_flag
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except Exception as e:
        print("Error opening serial:", e)
        sys.exit(1)
    print("Connected to", PORT, "-> logging to", CSV)

    t_s = threading.Thread(target=sender, args=(ser,), daemon=True)
    t_r = threading.Thread(target=reader, args=(ser,), daemon=True)
    t_s.start(); t_r.start()

    with open(CSV, "w", encoding="utf-8") as f:
        f.write("timestamp,event\n")
        try:
            while True:
                try:
                    ts, evt = q.get(timeout=0.2)
                    f.write(f"{ts:.3f},{evt}\n")
                    f.flush()
                except queue.Empty:
                    pass
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            stop_flag = True
            time.sleep(0.3)
            ser.close()
            print("Saved:", os.path.abspath(CSV))

if __name__ == "__main__":
    main()
