import test from 'node:test'
import assert from 'node:assert/strict'
import { reconstructSequence, sequenceIssue } from '../src/sequence.ts'
import type { PitchResult, SequencePitch } from '../src/sequence.ts'

const types = ['FF', 'SL']
const pitch = (result: PitchResult, extras: Partial<SequencePitch> = {}): SequencePitch => ({ pitch_type: 'FF', zone: null, velocity: null, result, ...extras })

test('a full sequence reconstructs count, and two-strike fouls do not end a plate appearance', () => {
  const sequence = [pitch('ball'), pitch('called_strike'), pitch('swinging_strike'), pitch('foul')]
  assert.deepEqual(reconstructSequence(sequence, types), { balls: 1, strikes: 2, terminal: false, error: null })
  assert.equal(sequenceIssue(sequence, types, 1, 2), null)
  assert.match(sequenceIssue(sequence, types, 2, 2)!, /球數與序列不一致/)
})

test('empty history supports manual count, while walk, strikeout and in-play stop prediction', () => {
  assert.equal(sequenceIssue([], types, 3, 2), null)
  for (const sequence of [Array.from({ length: 4 }, () => pitch('ball')), Array.from({ length: 3 }, () => pitch('called_strike')), [pitch('in_play')]]) {
    assert.equal(reconstructSequence(sequence, types).terminal, true)
    assert.match(sequenceIssue(sequence, types, 0, 0)!, /沒有下一球可預測/)
    assert.match(reconstructSequence([...sequence, pitch('ball')], types).error!, /已結束打席/)
  }
})

test('optional measurements remain missing, invalid measurements and unsupported codes are rejected', () => {
  assert.equal(reconstructSequence([pitch('ball')], types).error, null)
  assert.equal(reconstructSequence([pitch('ball', { zone: 0, velocity: 40 }), pitch('foul', { zone: 12, velocity: 180 })], types).error, null)
  for (const value of [39, 181, NaN, Infinity]) assert.match(reconstructSequence([pitch('ball', { velocity: value })], types).error!, /球速/)
  for (const value of [-1, 13, 1.5]) assert.match(reconstructSequence([pitch('ball', { zone: value })], types).error!, /落點/)
  assert.match(reconstructSequence([pitch('ball', { pitch_type: '???' })], types).error!, /球種/)
  assert.match(reconstructSequence(Array.from({ length: 17 }, () => pitch('foul')), types).error!, /最多/)
})

test('sixteen pitches remain valid when repeated two-strike fouls keep the PA alive', () => {
  const sequence = Array.from({ length: 16 }, () => pitch('foul'))
  assert.deepEqual(reconstructSequence(sequence, types), { balls: 0, strikes: 2, terminal: false, error: null })
  assert.equal(sequenceIssue(sequence, types, 0, 2), null)
})

test('unsupported result values are not silently counted as strikes', () => {
  const malformed = { ...pitch('ball'), result: 'hit_by_pitch' } as unknown as SequencePitch
  assert.match(reconstructSequence([malformed], types).error!, /投球結果/)
})
