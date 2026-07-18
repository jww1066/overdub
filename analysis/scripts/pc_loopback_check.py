#!/usr/bin/env python3
"""Drive a real stereo play+record through the PC's default audio devices to test a physical
loopback plug (prototype-plan.md Test 1 "Hardware status") -- a second opinion on BurnInTest's
"corrupt audio input on left channel" verdict, built from this repo's own already-validated
matched-filter instrument (`overdub_analysis.calibration_click`/`pc_loopback`) instead of trusting
a third-party tool's undocumented distortion analysis.

Plays two spectrally-distinct chirps simultaneously (left channel: 500-1500 Hz, right channel:
2500-4000 Hz), records the PC's default input at the same time, and reports a verdict per channel:

    ok         both templates as expected -- the plug loops back cleanly on this side
    swapped    this channel's recording matches the OTHER channel's chirp -- a wiring/pin-
               standard mismatch (e.g. CTIA vs OMTP), not corruption
    no-signal  neither template detected -- open circuit, or a signal too degraded to recognize
    ambiguous  something detected but not cleanly attributable to either side (real crosstalk)

Requires the PassMark plug to already be inserted, and Windows' default playback AND default
recording devices both set to the port it's in (Settings > Sound, or the taskbar speaker icon) --
sounddevice plays/records on whatever the OS default is, so a mismatched default device makes this
report on the wrong hardware silently.

Usage (from analysis/ via the venv, after `pip install -e .[pcloopback]`):
    .venv/Scripts/python.exe scripts/pc_loopback_check.py
    .venv/Scripts/python.exe scripts/pc_loopback_check.py --rate 48000 --output-wav capture.wav

Exit code is non-zero if either channel's verdict is not "ok".
"""

from __future__ import annotations

import argparse

import numpy as np

from overdub_analysis.pc_loopback import build_test_signal, diagnose_stereo_capture


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rate", type=int, default=48000, help="sample rate (Hz)")
    parser.add_argument(
        "--output-wav", default=None,
        help="optional path to save the raw stereo capture for manual inspection",
    )
    parser.add_argument("--quality-floor-db", type=float, default=10.0)
    parser.add_argument("--crosstalk-margin-db", type=float, default=6.0)
    parser.add_argument(
        "--list-devices", action="store_true",
        help="print all sounddevice-visible playback/recording devices with their index, then exit "
        "-- use this to find the PassMark plug's actual device index before trusting a result, "
        "since a run against the OS default device is silent about which hardware it used",
    )
    parser.add_argument(
        "--input-device", default=None,
        help="input device index or name substring (default: OS default recording device)",
    )
    parser.add_argument(
        "--output-device", default=None,
        help="output device index or name substring (default: OS default playback device)",
    )
    args = parser.parse_args()

    try:
        import sounddevice as sd
    except ImportError:
        print(
            "sounddevice is not installed -- run "
            "`.venv/Scripts/python.exe -m pip install sounddevice` "
            "(or `pip install -e .[pcloopback]`) first"
        )
        return 2

    if args.list_devices:
        print(sd.query_devices())
        return 0

    def _resolve(spec: str | None) -> int | None:
        if spec is None:
            return None
        try:
            return int(spec)
        except ValueError:
            pass
        devices = sd.query_devices()
        matches = [i for i, d in enumerate(devices) if spec.lower() in d["name"].lower()]
        if not matches:
            raise SystemExit(f"no device name contains '{spec}' -- run --list-devices to see options")
        if len(matches) > 1:
            names = ", ".join(f"{i}:{devices[i]['name']}" for i in matches)
            raise SystemExit(f"'{spec}' matches multiple devices ({names}) -- use an index instead")
        return matches[0]

    input_device = _resolve(args.input_device)
    output_device = _resolve(args.output_device)
    input_name = (
        sd.query_devices(input_device)["name"] if input_device is not None
        else sd.query_devices(kind="input")["name"]
    )
    output_name = (
        sd.query_devices(output_device)["name"] if output_device is not None
        else sd.query_devices(kind="output")["name"]
    )
    print(f"input device: {input_name}  ({'explicit' if input_device is not None else 'OS default'})")
    print(f"output device: {output_name}  ({'explicit' if output_device is not None else 'OS default'})")

    sig = build_test_signal(args.rate)
    play_buf = np.column_stack([sig.left, sig.right]).astype(np.float32)

    print(f"rate: {args.rate} Hz  playing+recording {play_buf.shape[0] / args.rate:.2f}s "
          f"(left: 500-1500 Hz chirp, right: 2500-4000 Hz chirp)")
    if input_device is None or output_device is None:
        print("using an OS-default device for at least one side -- pass --input-device/"
              "--output-device (see --list-devices) if the plug isn't actually the OS default.")

    rec_buf = sd.playrec(
        play_buf, samplerate=args.rate, channels=2, blocking=True,
        device=(input_device, output_device),
    )
    sd.wait()

    captured_left = rec_buf[:, 0]
    captured_right = rec_buf[:, 1]

    if args.output_wav:
        from scipy.io import wavfile

        wavfile.write(args.output_wav, args.rate, rec_buf.astype(np.float32))
        print(f"saved raw capture: {args.output_wav}")

    left_v, right_v = diagnose_stereo_capture(
        captured_left, captured_right, args.rate, sig,
        quality_floor_db=args.quality_floor_db,
        crosstalk_margin_db=args.crosstalk_margin_db,
    )

    print()
    print(f"{'channel':<8} {'verdict':<10} {'own_db':>8} {'cross_db':>9} {'own_offset_ms':>14}")
    print("-" * 55)
    for v in (left_v, right_v):
        print(f"{v.channel:<8} {v.verdict:<10} {v.own_quality_db:>8.1f} {v.cross_quality_db:>9.1f} "
              f"{v.own_offset_ms:>14.2f}")
    print()

    both_ok = left_v.verdict == "ok" and right_v.verdict == "ok"
    if both_ok:
        print("PASS: both channels loop back cleanly and identifiably.")
    else:
        print("FAIL: at least one channel did not read 'ok' -- see verdicts above.")
        if left_v.verdict == "swapped" or right_v.verdict == "swapped":
            print("  'swapped' points to a wiring/pin-standard mismatch (e.g. CTIA vs OMTP),")
            print("  not a corrupted/defective plug.")
        if left_v.verdict == "no-signal" or right_v.verdict == "no-signal":
            print("  'no-signal' points to an open circuit or a severely degraded connection")
            print("  on that channel -- consistent with a physically defective plug/contact.")

    return 0 if both_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
