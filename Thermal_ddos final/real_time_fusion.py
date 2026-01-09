# real_time_fusion.py
# Realtime fusion + plotting of host CPU vs Arduino TempEMA
# Usage: python real_time_fusion.py
# Requires: pip install psutil pyserial matplotlib numpy

import time, sys, threading, queue
import psutil, serial
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

PORT = "COM5"       # << change if needed
BAUD = 115200
SEND_INTERVAL = 0.5   # seconds, host telemetry send rate
SAMPLE_INTERVAL = 0.25 # expected Arduino sample interval (approx)

# fusion window settings
WINDOW_SECS = 8.0
WIN_SAMPLES = int(WINDOW_SECS / SAMPLE_INTERVAL)  # ~32
if WIN_SAMPLES < 4: WIN_SAMPLES = 4

# fusion weights & thresholds (tune these)
W_DELTA = 0.45
W_SLOPE = 0.25
W_HOST  = 0.30
SCORE_THRESH = 0.80
CORR_THRESH  = 0.55

q = queue.Queue()
stop_flag = False

# Parsed buffers (timestamps, hostCPU, tempEMA, slope)
ts_buf = []
host_buf = []
temp_buf = []
slope_buf = []

# Thread: send host telemetry
def sender(ser):
    global stop_flag
    while not stop_flag:
        cpu = psutil.cpu_percent(interval=None)/100.0
        try:
            ser.write(f"HOST,CPU:{cpu:.3f}\n".encode('utf-8'))
        except Exception as e:
            print("Write error:", e); break
        q.put(("NOTE", time.time(), f"HOST_OUT,{cpu:.3f}"))
        time.sleep(SEND_INTERVAL)

# Thread: read serial lines from Arduino
def reader(ser):
    global stop_flag
    while not stop_flag:
        try:
            line = ser.readline().decode('utf-8', errors='replace').strip()
        except Exception as e:
            print("Read error:", e); break
        if not line:
            continue
        t = time.time()
        q.put(("ARDUINO", t, line))

# compute Pearson correlation
def pearson(x, y):
    if len(x) < 3: return 0.0
    ax = np.array(x); ay = np.array(y)
    if ax.std() == 0 or ay.std() == 0: return 0.0
    return float(np.corrcoef(ax, ay)[0,1])

# compute score
def compute_score(delta, slope, hostcpu):
    norm_delta = np.clip(delta / max(1e-3, TEMP_ATTACK), 0.0, 1.0)
    norm_slope = np.clip(slope / max(1e-3, SLOPE_HIGH_CPS), 0.0, 1.0)
    score = W_DELTA*norm_delta + W_SLOPE*norm_slope + W_HOST*hostcpu
    return score

# We'll import TEMP_ATTACK and SLOPE_HIGH_CPS from the sketch values here:
TEMP_ATTACK = 7.5    # must match your Arduino config (°C delta)
SLOPE_HIGH_CPS = 0.10

# plotting setup
plt.ion()
fig, (ax1, ax2) = plt.subplots(2,1, figsize=(8,6), sharex=True)
line_temp, = ax1.plot([], [], label="TempEMA (°C)")
line_host, = ax1.plot([], [], label="Host CPU (frac)")
ax1.legend(loc='upper left')
ax1.set_ylabel("Temp °C / Host frac")
ax2.set_xlabel("Time (s)")
line_score, = ax2.plot([], [], label="Score")
line_corr, = ax2.plot([], [], label="Corr")
ax2.legend(loc='upper left')
ax2.set_ylabel("Score / Corr")

start_time = time.time()

# animation update
def update_plot(frame):
    # drain queue
    global ts_buf, host_buf, temp_buf, slope_buf
    while True:
        try:
            src, t, line = q.get_nowait()
        except queue.Empty:
            break
        if src == "NOTE":
            # optional: we could record host-out notes
            pass
        else:
            # parse lines
            # preferred format: DATA,<ms>,<temp>,<slope>,<host>
            if line.startswith("DATA,"):
                try:
                    parts = line.split(",")
                    tms = float(parts[1])/1000.0
                    tnow = start_time + tms/ (1.0)  # approximate
                    temp = float(parts[2])
                    slope = float(parts[3])
                    host = float(parts[4])
                except Exception:
                    continue
            else:
                # fallback parsing: look for TempEMA and host
                temp = None; slope = None; host = None
                if "TempEMA=" in line:
                    try:
                        # parse TempEMA=xx
                        idx = line.find("TempEMA=")
                        rest = line[idx+8:]
                        temp = float(rest.split(",")[0])
                    except: temp=None
                if "dT/s=" in line:
                    try:
                        idx = line.find("dT/s=")
                        slope = float(line[idx+5:].split(",")[0])
                    except: slope=None
                # host is updated by sender; we can keep last known host value
                # we also capture HOST_OUT entries if present
                if line.startswith("HOST,"):
                    try:
                        host = float(line.split("CPU:")[1])
                    except: host=None

                # If any fields missing, try to reuse last values
                if temp is None and len(temp_buf)>0:
                    temp = temp_buf[-1]
                if slope is None and len(slope_buf)>0:
                    slope = slope_buf[-1]
                if host is None and len(host_buf)>0:
                    host = host_buf[-1]
                if temp is None or slope is None or host is None:
                    continue

                tnow = t

            # append
            ts_buf.append(tnow - start_time)
            temp_buf.append(temp)
            slope_buf.append(slope)
            host_buf.append(host)
            # keep window size
            while len(ts_buf) > WIN_SAMPLES:
                ts_buf.pop(0); temp_buf.pop(0); slope_buf.pop(0); host_buf.pop(0)

    if len(ts_buf) == 0:
        return line_temp, line_host, line_score, line_corr

    # compute delta = temp - last BASE (we don't know BASE here; we approximate by taking min of temp window)
    # Better: you can hardcode BASE_TEMP from Arduino print; here we approximate baseline as min(temp_buf)
    base_est = min(temp_buf)
    delta = [t - base_est for t in temp_buf]

    # compute pointwise score and global score (use last sample values to decide)
    last_delta = delta[-1]
    last_slope = slope_buf[-1]
    last_host = host_buf[-1]
    score_now = compute_score(last_delta, last_slope, last_host)
    corr = pearson(temp_buf, host_buf)

    # plot series
    xs = np.array(ts_buf) - ts_buf[0]
    ax1.relim(); ax1.autoscale_view()
    ax2.relim(); ax2.autoscale_view()

    line_temp.set_data(xs, temp_buf)
    line_host.set_data(xs, host_buf)
    line_score.set_data(xs, [compute_score(d,s,h) for d,s,h in zip(delta, slope_buf, host_buf)])
    line_corr.set_data(xs, [pearson(temp_buf[max(0,i-WIN_SAMPLES+1):i+1], host_buf[max(0,i-WIN_SAMPLES+1):i+1]) for i in range(len(xs))])

    # draw decision text
    ax1.set_xlim(xs[0], xs[-1]+0.1)
    ax1.set_ylim(min(min(temp_buf), min(host_buf)) - 1, max(max(temp_buf), max(host_buf)) + 1)
    ax2.set_ylim(-0.05, 1.05)

    # Show numeric status on figure
    fig.suptitle(f"Score={score_now:.3f} Corr={corr:.3f} ΔT={last_delta:.2f} °C Host={last_host:.2f}")

    # Decision: if score & corr cross thresholds -> flag attack
    if score_now >= SCORE_THRESH and corr >= CORR_THRESH:
        # draw red border or print
        ax1.set_facecolor((1.0, 0.9, 0.9))
        ax2.set_facecolor((1.0, 0.9, 0.9))
        # you may choose to send a TEST or ALERT to Arduino here
        try:
            # one-time send of TEST
            ser.write(b"TEST\n")
        except:
            pass
    else:
        ax1.set_facecolor((1.0, 1.0, 1.0))
        ax2.set_facecolor((1.0, 1.0, 1.0))

    # update plotted lines
    ax1.relim(); ax1.autoscale_view()
    ax2.relim(); ax2.autoscale_view()
    return line_temp, line_host, line_score, line_corr

if __name__ == "__main__":
    try:
        ser = serial.Serial(PORT, BAUD, timeout=1)
    except Exception as e:
        print("Error opening serial:", e); sys.exit(1)
    print("Connected to", PORT)
    t_send = threading.Thread(target=sender, args=(ser,), daemon=True)
    t_read = threading.Thread(target=reader, args=(ser,), daemon=True)
    t_send.start(); t_read.start()

    ani = FuncAnimation(fig, update_plot, interval=500)
    plt.show(block=True)

    stop_flag = True
    ser.close()
    print("Exiting.")
