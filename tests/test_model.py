import pytest

from custom_components.changhuxi.model import decode, speed_points


def test_sentinels_do_not_report_clean_air():
    result = decode({31: 0, 32: 0, 37: 4, 3: 1073741824, 13: 29825, 14: 2900})
    assert result["pm25"] is None
    assert result["temperature"] == 25.1
    assert result["humidity"] == 29
    assert result["percentage"] == 0


@pytest.mark.parametrize("percentage,gear", [(1, 1), (17, 2), (50, 3), (100, 6)])
def test_discrete_speed(percentage, gear):
    assert speed_points(percentage) == {31: 1, 32: 1, 37: gear}


@pytest.mark.parametrize("value", [True, -1, 101, float("nan"), float("inf"), "50"])
def test_invalid_speed(value):
    with pytest.raises(ValueError):
        speed_points(value)


def test_zero_speed_is_off():
    assert speed_points(0) == {31: 0}


def test_unknown_mode_does_not_invent_a_speed():
    assert decode({31: 1, 32: 0, 37: 4})["percentage"] is None
    assert decode({31: 1, 32: 3, 37: 4})["preset_mode"] == "sleep"
