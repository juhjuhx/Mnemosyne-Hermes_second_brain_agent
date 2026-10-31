"""capacity_gate.py — DIT 2.2 P12.2-D: Phase 4 C4 storage reservation.

A pre-encode capacity check that RESERVES the estimated staging +
output bytes on the destination volume — not merely a percentage
warning. The census' 15% low-space threshold remains ADVISORY
(`advisory_low_space` is reported on the result, never blocks)
until separately authorized.

Facts, not guesses: the default free-space probe reads the OS
(`shutil.disk_usage`); a caller-supplied probe object (with
`.free`/`.total`) is only for tests / remote volumes.

    required = (staging_estimate + output_estimate) * safety_factor
    block    = required > free

`output_estimate == 0` (unknown size) is never "no reservation": a
hard floor (`MIN_OUTPUT_RESERVATION_BYTES`) applies, because a 0-byte
demand must not defeat the reservation.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass

#: A 1 MiB floor when the output estimate is unknown (0).
MIN_OUTPUT_RESERVATION_BYTES = 1 << 20

#: The census' advisory low-space threshold. REPORTED, not blocking —
#: changing it to a hard gate requires separate authorization.
ADVISORY_LOW_SPACE_FRACTION = 0.15


class CapacityShortError(Exception):
    """The destination volume cannot reserve the estimated staging +
    output bytes; the encode must not start (fail-closed)."""


@dataclass(frozen=True)
class CapacityDecision:
    ok: bool
    required_bytes: int
    free_bytes: int
    advisory_low_space: bool
    detail: str = ""


def free_space_bytes(path) -> int:
    """The OS truth for free bytes on the volume holding `path`."""
    return shutil.disk_usage(path).free


def check_capacity(
    probe,
    *,
    estimated_staging_bytes: int,
    estimated_output_bytes: int,
    safety_factor: float = 1.0,
) -> CapacityDecision:
    """Reserve estimated staging + output capacity on `probe`'s volume.

    `probe` is either a real path (via `free_space_bytes` semantics —
    callers should pass a `DiskProbe`) or any object with `.free` /
    `.total` attributes. Raises `CapacityShortError` when the
    requirement (factor applied to the sum, with the 0-output floor)
    exceeds the free bytes.
    """
    if safety_factor < 1.0:
        raise ValueError(
            "safety_factor must be >= 1.0 (it only inflates the "
            f"reservation, never shrinks it); got {safety_factor}"
        )
    free = getattr(probe, "free", None)
    total = getattr(probe, "total", None)
    if not isinstance(free, int) or not isinstance(total, int):
        raise CapacityShortError(
            f"unusable free-space probe (free={free!r}, total={total!r}) "
            "— a 0/unknown reservation is a fail, not a pass"
        )
    if free <= 0 or total <= 0:
        raise CapacityShortError(
            f"unusable free-space probe (free={free}, total={total}) — "
            "a 0/unknown reservation is a fail, not a pass"
        )
    est_output = int(estimated_output_bytes)
    if est_output < 0:
        raise ValueError("estimated_output_bytes must be >= 0")
    if est_output == 0:
        # Unknown output size: still reserve a floor — a 0 demand must
        # not mean "no reservation at all".
        est_output = MIN_OUTPUT_RESERVATION_BYTES
    est_staging = max(int(estimated_staging_bytes), 0)
    raw_sum = est_staging + est_output
    required = int(raw_sum * safety_factor)

    if required > free:
        raise CapacityShortError(
            f"destination cannot reserve {required} bytes "
            f"(staging {est_staging} + output floor {est_output}, x "
            f"{safety_factor}); only {free} free of {total} "
        )
    advisory = (free / total) < ADVISORY_LOW_SPACE_FRACTION
    return CapacityDecision(
        ok=True,
        required_bytes=raw_sum,
        free_bytes=free,
        advisory_low_space=advisory,
        detail="reserved",
    )


class DiskProbe:
    """A real-volume probe: reads `shutil.disk_usage` on demand."""

    def __init__(self, path):
        self.path = path

    @property
    def free(self) -> int:
        return free_space_bytes(self.path)

    @property
    def total(self) -> int:
        return shutil.disk_usage(self.path).total
