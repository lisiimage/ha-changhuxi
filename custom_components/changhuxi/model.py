"""Purifier datapoint decoding and validation, based on the Android model."""

import math

from .const import MODES

SENTINELS = {1073741824, -2147483648, -1073741824}


def decode(points: dict[int, int]) -> dict:
    """Never translate sensor sentinel values into apparently clean air."""
    power = points.get(31)
    mode = points.get(32)
    gear = points.get(37)
    pm = points.get(3)
    temperature = points.get(13)
    humidity = points.get(14)
    rpm = points.get(2)
    return {
        "power": power == 1 if power in (0, 1, 2) else None,
        "preset_mode": next((k for k, v in MODES.items() if v == mode), None),
        "percentage": 0
        if power == 0
        else (
            100
            if mode == 2
            else 17
            if mode == 3
            else round(gear * 100 / 6)
            if mode == 1 and gear in range(1, 7)
            else None
        ),
        "gear": gear,
        "pm25": pm if pm is not None and 0 <= pm < 10000 else None,
        "temperature": round(((temperature & 65535) - 27315) / 100, 2)
        if temperature is not None and temperature not in SENTINELS | {55365}
        else None,
        "humidity": (humidity & 65535) / 100
        if humidity is not None
        and humidity not in SENTINELS | {28050}
        and 0 <= (humidity & 65535) <= 10000
        else None,
        "rpm": rpm if rpm is not None and 0 <= rpm < 100000 else None,
        "child_lock": points.get(33) == 1 if points.get(33) in (0, 1) else None,
        "brightness": points.get(35),
        "error_code": points.get(5),
    }


def speed_points(percentage: int) -> dict[int, int]:
    """Map percentages onto the hardware's six discrete manual gears."""
    if (
        isinstance(percentage, bool)
        or not isinstance(percentage, (int, float))
        or not math.isfinite(percentage)
        or not 0 <= percentage <= 100
    ):
        raise ValueError("Percentage must be between 0 and 100")
    return (
        {31: 0} if percentage == 0 else {31: 1, 32: 1, 37: max(1, math.ceil(percentage * 6 / 100))}
    )
