import app as A


def _d(icon, t=27, h=76, w=8):
    return {"temperature": t, "humidity": h, "wind_speed": w, "icon": icon}


def test_rain_is_never_called_good_for_field_work():
    assert "raining" in A._owm_tip(_d("cloud-rain"))
    assert "Thunderstorm" in A._owm_tip(_d("bolt"))
    assert "good for field" in A._owm_tip(_d("sun", h=60))
    assert "good for field" not in A._owm_tip(_d("cloud-rain", h=60))
