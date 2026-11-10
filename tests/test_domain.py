import math

import pytest

from src.domain import advance_count, zone13


@pytest.mark.parametrize('x,y,z',[(-49,59,0),(0,0,4),(49,-59,8),(50,60,2),
    (0,90,9),(80,0,10),(0,-90,11),(-80,0,12),(100,120,9),(-100,-120,11)])
def test_zone_geometry_and_outer_diagonal_ties(x,y,z):
    assert zone13(x,y)==z


@pytest.mark.parametrize('x,y',[(None,0),('',0),('NaN',0),(math.inf,10),(501,0),(0,601)])
def test_missing_and_outlier_coordinates_are_not_valid_zones(x,y):
    assert zone13(x,y) is None


def test_two_strike_foul_does_not_end_plate_appearance():
    assert advance_count(1,2,'F')==(1,2,False)
    assert advance_count(1,2,'FOUL_BUNT')==(1,3,True)
    assert advance_count(1,2,'FT')==(1,3,True)
    assert advance_count(3,1,'B')==(4,1,True)
    assert advance_count(0,0,'H')==(0,0,True)
    with pytest.raises(ValueError):
        advance_count(0,0,'unknown')
