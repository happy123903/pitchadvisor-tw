import test from 'node:test'
import assert from 'node:assert/strict'
import { validateDemo } from '../src/demo.ts'

const response = { model_version: 'frozen', data_version: 'data', data_cutoff: '2024-08-14', pitch_probabilities: [], zone_probabilities: [], recommendations: [] }
const item = { id: 'case-1', title: '固定案例', request: { pitcher_id: 'p', batter_id: 'b', state: { balls: 0, strikes: 0, outs: 0, bases: [false, false, false] }, sequence: [] }, response }
const bundle = () => ({ model_version: 'frozen', data_version: 'data', data_cutoff: '2024-08-14', bundle_sha256: 'a'.repeat(64), cases: [structuredClone(item)] })

test('fixed cases retain frozen inputs and outputs', () => assert.deepEqual(validateDemo(bundle()).cases[0], item))
test('fixed cases reject mismatched versions and duplicate IDs', () => {
  const mismatch = bundle(); mismatch.cases[0].response.model_version = 'another'
  assert.throws(() => validateDemo(mismatch), /不一致/)
  const duplicate = bundle(); duplicate.cases.push(structuredClone(item))
  assert.throws(() => validateDemo(duplicate), /不一致/)
  assert.throws(() => validateDemo({ ...bundle(), cases: [] }), /不完整/)
})
