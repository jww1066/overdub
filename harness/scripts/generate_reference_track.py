"""Generates the synthetic placeholder reference track (click track) used by the Test 2 harness.

Not a real beatbox recording -- see reference_track_README.md next to the generated output file.
Uses only the Python stdlib `wave` module, no new dependency. The output WAV is gitignored (never
committed -- see CLAUDE.md/memory: no audio files in Git); run this script to (re)create it locally.
"""
import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 48000
DURATION_S = 15.0
TEMPO_BPM = 120.0
CLICK_DURATION_S = 0.03

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "src" / "main" / "assets" / "reference_track.wav"


def make_click(freq_hz: float, amplitude: float) -> list[int]:
    n = int(SAMPLE_RATE * CLICK_DURATION_S)
    samples = []
    for i in range(n):
        t = i / SAMPLE_RATE
        envelope = math.exp(-40.0 * t)  # fast decay, percussive
        value = amplitude * envelope * math.sin(2 * math.pi * freq_hz * t)
        samples.append(int(value))
    return samples


def main() -> None:
    total_samples = int(SAMPLE_RATE * DURATION_S)
    beat_period_s = 60.0 / TEMPO_BPM
    beat_period_samples = int(SAMPLE_RATE * beat_period_s)

    pcm = [0] * total_samples

    kick = make_click(90.0, 22000)
    hihat = make_click(3500.0, 9000)

    beat_index = 0
    pos = 0
    while pos < total_samples:
        # alternate a low "kick" on the downbeat and a higher "hihat" on the off-beat,
        # a crude stand-in rhythm -- not meant to resemble real beatboxing.
        click = kick if beat_index % 2 == 0 else hihat
        for i, s in enumerate(click):
            idx = pos + i
            if idx >= total_samples:
                break
            pcm[idx] = max(-32768, min(32767, pcm[idx] + s))
        pos += beat_period_samples
        beat_index += 1

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUTPUT_PATH), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(SAMPLE_RATE)
        wav_file.writeframes(struct.pack(f"<{len(pcm)}h", *pcm))

    print(f"wrote {OUTPUT_PATH}: {total_samples} samples, {DURATION_S}s at {SAMPLE_RATE}Hz")


if __name__ == "__main__":
    main()
