import requests
import numpy as np
from obspy import read
from obspy.core import UTCDateTime
from scipy.signal import resample, butter, filtfilt
import soundfile as sf
import subprocess
import tempfile
import os


# -----------------------------
# 🔧 필터 (저주파 노이즈 제거)
# -----------------------------
def highpass(data, fs, cutoff=1.0):
    b, a = butter(4, cutoff / (fs / 2), btype='high')
    return filtfilt(b, a, data)


# -----------------------------
# 🔊 Gain / Limiter / Compressor
# -----------------------------
def apply_gain(audio, gain_db=0.0, auto_limit=True, compress=False):
    # dB → linear
    gain = 10 ** (gain_db / 20.0)
    audio = audio * gain

    # 🔹 Compressor (soft clipping)
    if compress:
        audio = np.tanh(audio)

    # 🔹 Limiter (clipping 방지)
    if auto_limit:
        max_val = np.max(np.abs(audio))
        if max_val > 1.0:
            audio = audio / max_val

    return audio


# -----------------------------
# 🎧 메인 함수
# -----------------------------
def fdsn_to_mp3(
    starttime,
    duration,
    network,
    station,
    location,
    channel,
    server="http://172.31.100.100",
    output_sample_rate=44100,
    output_file="output.mp3",
    gain_db=0.0,
    auto_limit=True,
    compress=False,
    highpass_filter=True
):
    """
    FDSNWS → MiniSEED → Audio (MP3)
    """

    # -----------------------------
    # 1. 시간 설정
    # -----------------------------
    t0 = UTCDateTime(starttime)
    t1 = t0 + duration

    # -----------------------------
    # 2. FDSNWS 요청
    # -----------------------------
    url = (
        f"{server}/fdsnws/dataselect/1/query"
        f"?net={network}&sta={station}&loc={location}&cha={channel}"
        f"&starttime={t0.isoformat()}&endtime={t1.isoformat()}"
    )

    print(f"[INFO] Request: {url}")

    response = requests.get(url)
    response.raise_for_status()

    # -----------------------------
    # 3. MiniSEED 저장
    # -----------------------------
    with tempfile.NamedTemporaryFile(delete=False) as tmp_mseed:
        tmp_mseed.write(response.content)
        mseed_path = tmp_mseed.name

    print(f"[INFO] MiniSEED saved: {mseed_path}")

    # -----------------------------
    # 4. 데이터 읽기
    # -----------------------------
    st = read(mseed_path)
    tr = st[0]
    data = tr.data.astype(np.float64)

    # -----------------------------
    # 5. 전처리
    # -----------------------------
    data = data - np.mean(data)

    # optional highpass
    if highpass_filter:
        data = highpass(data, tr.stats.sampling_rate)

    # normalize
    max_val = np.max(np.abs(data))
    if max_val > 0:
        data = data / max_val

    # -----------------------------
    # 6. 가청 주파수 변환
    # -----------------------------
    original_sr = tr.stats.sampling_rate
    print(f"[INFO] Original SR: {original_sr}")

    num_samples = int(len(data) * (output_sample_rate / original_sr))
    audio_data = resample(data, num_samples)

    # -----------------------------
    # 7. 🔊 Gain 적용
    # -----------------------------
    audio_data = apply_gain(
        audio_data,
        gain_db=gain_db,
        auto_limit=auto_limit,
        compress=compress
    )

    # -----------------------------
    # 8. WAV 저장
    # -----------------------------
    tmp_wav = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    wav_path = tmp_wav.name

    sf.write(wav_path, audio_data, output_sample_rate)

    print(f"[INFO] WAV saved: {wav_path}")

    # -----------------------------
    # 9. MP3 변환 (ffmpeg)
    # -----------------------------
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-i", wav_path,
        "-codec:a", "libmp3lame",
        "-qscale:a", "2",
        output_file
    ]

    subprocess.run(cmd, check=True)

    print(f"[INFO] MP3 saved: {output_file}")

    # -----------------------------
    # 10. 정리
    # -----------------------------
    os.remove(mseed_path)
    os.remove(wav_path)


# -----------------------------
# 🚀 실행 예시
# -----------------------------
if __name__ == "__main__":
    fdsn_to_mp3(
        starttime="2026-06-17T00:30:00",
        duration=600,
        network="KG",
        station="KMPMC",
        location="",
        channel="FXM",
        output_file="result.mp3",

        # 🔊 사운드 옵션
        gain_db=20,        # 10~30 추천
        auto_limit=True,   # 필수
        compress=True,     # 작은 신호 살림
        highpass_filter=True
    )