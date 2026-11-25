"""Throwaway capture spike: checks soundcard loopback, hot-plug visibility and silence behaviour.

Usage: .venv\\Scripts\\python tools\\spike_capture.py [seconds] [--tone]
  --tone  plays a 440 Hz tone for 2 s at t=2s on the default speaker so loopback has something to hear.
Connect/disconnect Bluetooth headphones while it runs to check hot-plug.
"""
import sys
import threading
import time

import numpy as np
import soundcard as sc

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1][0].isdigit() else 30.0
T0 = time.perf_counter()
stop = threading.Event()
active: dict[str, threading.Thread] = {}
stats: dict[str, dict] = {}


def reader(dev, label):
    st = stats.setdefault(label, {"blocks": 0, "frames": 0, "max_gap": 0.0, "max_rms": 0.0})
    last = None
    try:
        with dev.recorder(samplerate=48000, blocksize=4800) as rec:
            while not stop.is_set():
                data = rec.record(numframes=4800)
                now = time.perf_counter()
                if last is not None:
                    st["max_gap"] = max(st["max_gap"], now - last)
                last = now
                st["blocks"] += 1
                st["frames"] += len(data)
                st["max_rms"] = max(st["max_rms"], float(np.sqrt((data ** 2).mean())) if len(data) else 0.0)
    except Exception as e:  # noqa: BLE001 - spike
        print(f"[{now_s():6.2f}] {label}: reader ended: {e!r}")
    finally:
        active.pop(label, None)


def now_s():
    return time.perf_counter() - T0


def poll():
    while not stop.is_set():
        try:
            devs = sc.all_microphones(include_loopback=True)
        except Exception as e:  # noqa: BLE001
            print("enumerate failed", e)
            devs = []
        for d in devs:
            label = ("LOOP " if d.isloopback else "MIC  ") + d.name
            if label not in active:
                print(f"[{now_s():6.2f}] + {label}")
                t = threading.Thread(target=reader, args=(d, label), daemon=True)
                active[label] = t
                t.start()
        time.sleep(1.0)


def tone():
    time.sleep(2)
    sr = 48000
    t = np.arange(sr * 2) / sr
    sig = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    try:
        sc.default_speaker().play(sig, samplerate=sr)
    except Exception as e:  # noqa: BLE001
        print("tone failed", e)


threading.Thread(target=poll, daemon=True).start()
if "--tone" in sys.argv:
    threading.Thread(target=tone, daemon=True).start()
time.sleep(DURATION)
stop.set()
time.sleep(0.5)
print(f"\nAfter {DURATION:.0f}s:")
for label, st in stats.items():
    secs = st["frames"] / 48000
    print(f"  {label}: blocks={st['blocks']} audio={secs:.1f}s max_gap={st['max_gap']:.2f}s max_rms={st['max_rms']:.3f}")
