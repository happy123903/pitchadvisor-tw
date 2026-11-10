"""Shared, strict reconstruction of a complete current plate appearance.

An empty history means unavailable history, not a claimed 0-0 count. A supplied
history always starts at 0-0 and contains only pitches before the next prediction.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


MAX_SEQUENCE_LENGTH = 16
SEQUENCE_RESULTS = ('ball', 'called_strike', 'swinging_strike', 'foul', 'in_play')


class SequenceValidationError(ValueError):
    """A safe diagnostic code without echoing user input or credentials."""

    def __init__(self, code: str, message: str, index: int | None = None):
        super().__init__(message)
        self.code = code
        self.index = index


def reconstruct_count(sequence: Sequence[Mapping]) -> tuple[int, int, bool]:
    """Replay result labels, returning (balls, strikes, plate_appearance_ended).

    Terminal final pitches are returned to preprocessing as terminal, but a pitch
    after an ended PA is rejected. ``validate_sequence`` also rejects terminal
    histories because there is no next pitch to predict in that same PA.
    """
    balls = strikes = 0
    terminal = False
    for index, pitch in enumerate(sequence):
        if terminal:
            raise SequenceValidationError('history_after_pa_end',
                                          'History contains a pitch after the plate appearance ended.', index)
        result = pitch.get('result')
        if result not in SEQUENCE_RESULTS:
            raise SequenceValidationError('history_unknown_result',
                                          'History result must use a supported result label.', index)
        if result == 'ball':
            balls += 1
        elif result in ('called_strike', 'swinging_strike'):
            strikes += 1
        elif result == 'foul':
            strikes = min(2, strikes + 1)
        terminal = result == 'in_play' or balls >= 4 or strikes >= 3
    return balls, strikes, terminal


def validate_sequence(sequence, balls: int | None = None, strikes: int | None = None,
                      known_pitch_types=None) -> dict:
    """Validate the API/training history contract and optionally its current count.

    ``known_pitch_types`` is the trained model's vocabulary. Missing locations and
    speeds stay ``None`` so the feature builder can apply its learned masks.
    """
    if not isinstance(sequence, (list, tuple)):
        raise SequenceValidationError('history_invalid_type', 'History must be a list of pitches.')
    if len(sequence) > MAX_SEQUENCE_LENGTH:
        raise SequenceValidationError('history_too_long', 'History supports at most 16 pitches.')
    for index, pitch in enumerate(sequence):
        if not isinstance(pitch, Mapping):
            raise SequenceValidationError('history_invalid_pitch', 'Each history pitch must be an object.', index)
        if set(pitch) - {'pitch_type', 'zone', 'velocity', 'result'}:
            raise SequenceValidationError('history_extra_fields', 'History pitch contains unsupported fields.', index)
        pitch_type = pitch.get('pitch_type')
        if not isinstance(pitch_type, str) or not pitch_type or len(pitch_type) > 16:
            raise SequenceValidationError('history_invalid_pitch_type', 'History pitch type must be a supported code.', index)
        if known_pitch_types is not None and pitch_type not in known_pitch_types:
            raise SequenceValidationError('history_unknown_pitch_type',
                                          'History pitch type is not recognized by this model version.', index)
        zone = pitch.get('zone')
        if zone is not None and (type(zone) is not int or not 0 <= zone <= 12):
            raise SequenceValidationError('history_invalid_zone', 'History zone must be 0-12 or null.', index)
        velocity = pitch.get('velocity')
        if velocity is not None and (isinstance(velocity, bool) or not isinstance(velocity, (int, float))
                                     or not math.isfinite(velocity) or not 40 <= velocity <= 180):
            raise SequenceValidationError('history_invalid_velocity',
                                          'History velocity must be 40-180 km/h or null.', index)
    reconstructed_balls, reconstructed_strikes, terminal = reconstruct_count(sequence)
    if terminal:
        raise SequenceValidationError('history_pa_ended',
                                      'The plate appearance has ended; start a new plate appearance before predicting.')
    if sequence and ((balls is not None and balls != reconstructed_balls)
                     or (strikes is not None and strikes != reconstructed_strikes)):
        raise SequenceValidationError('history_count_mismatch',
                                      'State balls and strikes must match the complete history replayed from 0-0.')
    return {
        'provided': bool(sequence), 'length': len(sequence),
        'balls': reconstructed_balls if sequence else None,
        'strikes': reconstructed_strikes if sequence else None,
        'missing_zone_count': sum(pitch.get('zone') is None for pitch in sequence),
        'missing_velocity_count': sum(pitch.get('velocity') is None for pitch in sequence),
    }
