"""Offline signal-processing validation for the Overdub app.

See `doc/prototype-plan.md` (Test 2 step 1) and `doc/test2-step2-plan.md`.
"""

from overdub_analysis.gcc_phat import GccPhatResult, gcc_phat, gcc_phat_correlation
from overdub_analysis.synth import (
    add_noise_at_snr,
    broadband_click_train,
    delay,
)

__all__ = [
    "GccPhatResult",
    "gcc_phat",
    "gcc_phat_correlation",
    "add_noise_at_snr",
    "broadband_click_train",
    "delay",
]
