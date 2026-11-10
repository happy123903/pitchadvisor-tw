"""Shared baseball state rules. Coordinates follow Rebas' pitcher-view schema."""
from __future__ import annotations

import math

PITCH_NAMES = {'FF': '四縫線', 'SI': '伸卡／二縫線', 'FC': '卡特', 'SL': '滑球',
               'CU': '曲球', 'CH': '變速球', 'FO': '指叉', 'FS': '快速指叉',
               'KN': '蝴蝶球', 'EP': '小便球'}
RESULTS = ['ball', 'called_strike', 'swinging_strike', 'foul', 'in_play', 'hit_by_pitch', 'other']
ZONE_NAMES = ['左上', '中上', '右上', '左中', '正中', '右中', '左下', '中下', '右下',
              '帶外上方', '帶外右側', '帶外下方', '帶外左側']


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def zone13(x, y):
    """Width 100%, height 120%; exclusive outer sectors by normalized deviation.

    Rebas coordinates use strike-zone width as 100 (not centimeters); center 0.
    Outer diagonal ties belong to the vertical sector. Missing/outliers -> None.
    """
    x, y = number(x), number(y)
    if x is None or y is None or abs(x) > 500 or abs(y) > 600:
        return None
    if -50 <= x <= 50 and -60 <= y <= 60:
        col = min(2, int((x + 50) / (100 / 3)))
        row = min(2, int((60 - y) / 40))
        return row * 3 + col
    if abs(y / 60) >= abs(x / 50):
        return 9 if y > 0 else 11
    return 10 if x > 0 else 12


def advance_count(balls, strikes, code):
    """Return balls, strikes, terminal. Reject codes with unknown count semantics."""
    if code == 'B':
        balls += 1
    elif code in ('S', 'SW', 'FT', 'TRY_BUNT', 'FOUL_BUNT'):
        strikes += 1
    elif code == 'F':
        strikes = min(2, strikes + 1)
    elif code in ('H', 'BUNT'):
        return balls, strikes, True
    else:
        raise ValueError(f'Unknown pitch result code: {code}')
    return balls, strikes, balls >= 4 or strikes >= 3


def result_label(code, pa_result=None):
    if pa_result == 'HBP':
        return 'hit_by_pitch'
    return {'B': 'ball', 'S': 'called_strike', 'SW': 'swinging_strike',
            'FT': 'swinging_strike', 'TRY_BUNT': 'swinging_strike',
            'F': 'foul', 'FOUL_BUNT': 'foul', 'H': 'in_play', 'BUNT': 'in_play'}.get(code, 'other')


def state_key(balls, strikes, outs, bases):
    return f'{int(balls)}|{int(strikes)}|{int(outs)}|{int(bases)}'
