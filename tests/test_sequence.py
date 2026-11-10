import pytest

from src.sequence import SequenceValidationError, reconstruct_count, validate_sequence


def pitch(result='ball', **kwargs):
    return {'pitch_type':'FF','zone':None,'velocity':None,'result':result,**kwargs}


def test_missing_history_preserves_unknown_count_and_masks():
    summary=validate_sequence([],3,2,['FF'])
    assert summary=={'provided':False,'length':0,'balls':None,'strikes':None,
                     'missing_zone_count':0,'missing_velocity_count':0}
    history=[pitch(),pitch('called_strike',zone=4,velocity=145),pitch('foul')]
    summary=validate_sequence(history,1,2,['FF'])
    assert summary['length']==3
    assert summary['missing_zone_count']==summary['missing_velocity_count']==2
    assert summary['balls']==1 and summary['strikes']==2
    assert history[0]['zone'] is None and history[0]['velocity'] is None


def test_two_strike_fouls_do_not_end_the_pa():
    history=[pitch('called_strike'),pitch('swinging_strike')]+[pitch('foul')]*14
    assert reconstruct_count(history)==(0,2,False)
    assert validate_sequence(history,0,2,['FF'])['length']==16


@pytest.mark.parametrize('history',[
    [pitch()]*4,
    [pitch('called_strike')]*3,
    [pitch('swinging_strike')]*3,
    [pitch('in_play')],
])
def test_terminal_history_has_no_next_pitch(history):
    assert reconstruct_count(history)[2] is True
    with pytest.raises(SequenceValidationError) as error:
        validate_sequence(history)
    assert error.value.code=='history_pa_ended'
    with pytest.raises(SequenceValidationError) as error:
        reconstruct_count(history+[pitch()])
    assert error.value.code=='history_after_pa_end'


@pytest.mark.parametrize('history,code',[
    ([pitch()]*17,'history_too_long'),
    ([pitch(pitch_type='UNKNOWN')],'history_unknown_pitch_type'),
    ([pitch(zone=-1)],'history_invalid_zone'),
    ([pitch(zone=13)],'history_invalid_zone'),
    ([pitch(zone=True)],'history_invalid_zone'),
    ([pitch(zone=4.0)],'history_invalid_zone'),
    ([pitch(velocity=39)],'history_invalid_velocity'),
    ([pitch(velocity=181)],'history_invalid_velocity'),
    ([pitch(velocity=float('nan'))],'history_invalid_velocity'),
    ([pitch(velocity=True)],'history_invalid_velocity'),
    ([pitch(result='hit_by_pitch')],'history_unknown_result'),
    ([pitch(extra='field')],'history_extra_fields'),
    ([None],'history_invalid_pitch'),
])
def test_invalid_history_is_rejected(history,code):
    with pytest.raises(SequenceValidationError) as error:
        validate_sequence(history,known_pitch_types=['FF'])
    assert error.value.code==code


def test_history_cannot_claim_a_different_current_count():
    with pytest.raises(SequenceValidationError) as error:
        validate_sequence([pitch(),pitch('called_strike')],0,1,['FF'])
    assert error.value.code=='history_count_mismatch'


def test_inputs_at_speed_and_location_boundaries_are_preserved():
    history=[pitch(zone=0,velocity=40),pitch('foul',zone=12,velocity=180)]
    assert validate_sequence(history,1,1,['FF'])['missing_zone_count']==0
