import forecast as fc

# BBS Yearbook of Agricultural Statistics 2023, Table 2.1.1, 2022-23 (kg per acre); potato = production / area
BBS_2022_23 = {"rice": 1362, "wheat": 1494, "maize": 3718, "potato": 9273, "tomato": 6098, "brinjal": 5158,
               "onion": 5065, "lentil": 589, "mustard": 578, "jute": 851, "garlic": 3099, "ginger": 3259}


def test_typical_yield_matches_the_bbs_national_average():
    for crop, official in BBS_2022_23.items():
        lo, mid, hi = fc.YIELD_KG_PER_ACRE[crop]
        assert abs(mid - official) / official < 0.03, (crop, mid, official)   # rounded to the nearest ~50 kg


def test_ranges_are_ordered_and_every_crop_has_a_price_word():
    for crop, (lo, mid, hi) in fc.YIELD_KG_PER_ACRE.items():
        assert 0 < lo < mid < hi, crop
        assert crop in fc.PRICE_MATCH
    assert fc.UNVERIFIED <= set(fc.YIELD_KG_PER_ACRE)
