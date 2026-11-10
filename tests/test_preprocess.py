import json
import zipfile

from src.preprocess import flatten


def test_pre_pitch_count_not_copied_from_terminal_pa_and_nonpitch_not_counted(tmp_path):
    events=[{'type':'PITCH','pitchCode':c,'pitchType':'FF','coordX':'0','coordY':'0',
             'pitcherName':'Pitcher','batterName':'Batter','runners':[]} for c in ['S','F','F','B','H']]
    events.insert(3,{'type':'SUB','runners':[]})
    events[-1]['runners']=[{'isOut':True,'scored':False}]
    pa={'inning':1,'batterName':'Batter','pitcherName':'Pitcher','batterHand':'R','pitcherHand':'L',
        'outs':0,'bases':0,'balls':1,'strikes':2,'awayScores':0,'homeScores':0,
        'endOuts':1,'endBases':0,'endAwayScores':0,'endHomeScores':0,'result':'GO','events':events}
    game={'seasonId':'CPBL-2023-test','seq':1,'date':'2023-04-01','awayTeamId':'A','homeTeamId':'H',
        'awayPAList':[pa],'homePAList':[],'awayBatterBox':[{'playerId':'b','playerName':'Batter'}],
        'homePitcherBox':[{'playerId':'p','playerName':'Pitcher'}]}
    with zipfile.ZipFile(tmp_path/'fixture.zip','w') as archive:
        archive.writestr('CPBL-2023-G1.json',json.dumps(game))
        archive.writestr('combined-OpenData.json',json.dumps([game]))
    pitches,games,identities,audit=flatten(tmp_path)
    assert len(games)==1 and len(pitches)==5
    assert list(zip(pitches.balls,pitches.strikes))==[(0,0),(0,1),(0,2),(0,2),(1,2)]
    assert pitches.state_valid.all()
    assert pitches.pitcher_id.eq('p').all()
    assert pitches.runs_to_end.isna().all()  # Incomplete half inning isn't a full RE target.
    assert audit['event_types']['SUB']==1
