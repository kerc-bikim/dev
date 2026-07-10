import subprocess
import numpy as np
import threading
import queue
import time
import sys
import math

from obspy.clients.seedlink.easyseedlink import EasySeedLinkClient
from scipy.signal import resample_poly

# =========================
# 설정
# =========================
SEEDLINK_SERVER = "172.31.100.100"
NET = "KG"
STA = "KMPMC"
CHA = "FXM"

INPUT_SAMPLE_RATE = 5000
OUTPUT_SAMPLE_RATE = 22050

ICECAST_URL = "icecast://source:hackme@localhost:8000/stream.mp3"

# ★ 핵심 파라미터
BUFFER_SECONDS = 12     # 총 버퍼
PROCESS_SECONDS = 5     # 처리 단위
START_THRESHOLD = 10    # 시작 조건

RECONNECT_DELAY = 5

# =========================
# 공유 버퍼 (초 단위)
# =========================
raw_buffer = []
buffer_lock = threading.Lock()

audio_queue = queue.Queue(maxsize=200)

# =========================
# FFmpeg
# =========================
def start_ffmpeg():
    cmd = [
        "ffmpeg",
        "-loglevel", "error",
        "-fflags", "nobuffer",
        "-flags", "low_delay",
        "-f", "s16le",
        "-ar", str(OUTPUT_SAMPLE_RATE),
        "-ac", "1",
        "-i", "pipe:0",
        "-f", "mp3",
        "-b:a", "128k",
        ICECAST_URL
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE)

# =========================
# 리샘플링
# =========================
def resample_audio(data):
    gcd = math.gcd(INPUT_SAMPLE_RATE, OUTPUT_SAMPLE_RATE)
    return resample_poly(data, OUTPUT_SAMPLE_RATE//gcd, INPUT_SAMPLE_RATE//gcd)

# =========================
# Audio Processor
# =========================
class AudioProcessor:
    def __init__(self):
        self.prev_tail = None

    def process(self, chunk):
        # DC 제거
        chunk = chunk - np.mean(chunk)

        # Normalize
        max_val = np.max(np.abs(chunk))
        if max_val == 0:
            return None

        chunk = chunk / max_val

        # smoothing
        chunk = np.convolve(chunk, np.ones(5)/5, mode='same')

        # resample
        chunk = resample_audio(chunk)

        # crossfade
        if self.prev_tail is not None:
            fade_len = min(500, len(chunk), len(self.prev_tail))
            fade = np.linspace(0, 1, fade_len)

            chunk[:fade_len] = (
                self.prev_tail[:fade_len]*(1-fade) +
                chunk[:fade_len]*fade
            )

        self.prev_tail = chunk[-500:].copy()

        # limiter
        chunk = np.clip(chunk * 2.0, -1, 1)

        return (chunk * 32767).astype(np.int16)

processor = AudioProcessor()

# =========================
# SeedLink Thread (데이터 축적)
# =========================
class SeedLinkWorker(threading.Thread):
    def run(self):
        while True:
            try:
                print("[SeedLink] Connecting...")

                class Client(EasySeedLinkClient):
                    def on_data(self_inner, trace):
                        data = trace.data.astype(np.float32)

                        with buffer_lock:
                            raw_buffer.extend(data)

                            # 최대 버퍼 유지
                            max_samples = INPUT_SAMPLE_RATE * BUFFER_SECONDS
                            if len(raw_buffer) > max_samples:
                                del raw_buffer[:len(raw_buffer)-max_samples]

                client = Client(SEEDLINK_SERVER)
                client.select_stream(NET, STA, CHA)
                client.run()

            except Exception as e:
                print("[SeedLink] Reconnecting...", e)
                time.sleep(RECONNECT_DELAY)

# =========================
# Processing Thread (5초 단위 처리)
# =========================
class ProcessingWorker(threading.Thread):
    def run(self):
        started = False

        while True:
            time.sleep(0.1)

            with buffer_lock:
                buffer_len_sec = len(raw_buffer) / INPUT_SAMPLE_RATE

                if not started:
                    if buffer_len_sec >= START_THRESHOLD:
                        print("[Processor] Start playback")
                        started = True
                    else:
                        continue

                if buffer_len_sec < PROCESS_SECONDS:
                    continue

                # 5초 chunk 추출
                samples = int(INPUT_SAMPLE_RATE * PROCESS_SECONDS)
                chunk = np.array(raw_buffer[:samples])
                del raw_buffer[:samples]

            pcm = processor.process(chunk)
            if pcm is not None:
                audio_queue.put(pcm)

# =========================
# FFmpeg Thread
# =========================
class FFmpegWorker(threading.Thread):
    def run(self):
        ffmpeg = None

        while True:
            try:
                if ffmpeg is None or ffmpeg.poll() is not None:
                    print("[FFmpeg] Restarting...")
                    ffmpeg = start_ffmpeg()

                pcm = audio_queue.get()

                try:
                    ffmpeg.stdin.write(pcm.tobytes())
                except:
                    ffmpeg.kill()
                    ffmpeg = None

            except Exception as e:
                print("[FFmpeg] Error:", e)
                time.sleep(1)

# =========================
# Main
# =========================
if __name__ == "__main__":
    print("=== Buffered Stable Stream (10s buffer / 5s chunk) ===")

    t1 = SeedLinkWorker()
    t2 = ProcessingWorker()
    t3 = FFmpegWorker()

    t1.daemon = True
    t2.daemon = True
    t3.daemon = True

    t1.start()
    t2.start()
    t3.start()

    while True:
        time.sleep(1)