export const MAX_SEQUENCE_LENGTH = 16
export const PITCH_RESULTS = ['ball', 'called_strike', 'swinging_strike', 'foul', 'in_play'] as const
export type PitchResult = typeof PITCH_RESULTS[number]
export type SequencePitch = {
  pitch_type: string
  zone: number | null
  velocity: number | null
  result: PitchResult
}
export type SequenceState = {
  balls: number
  strikes: number
  terminal: boolean
  error: string | null
}

// An optional sequence represents the complete current plate appearance from 0–0.
export function reconstructSequence(sequence: SequencePitch[], pitchTypes: string[]): SequenceState {
  let balls = 0
  let strikes = 0
  let terminal = false
  const failed = (error: string): SequenceState => ({ balls, strikes, terminal, error })
  if (sequence.length > MAX_SEQUENCE_LENGTH) return failed(`最多可輸入 ${MAX_SEQUENCE_LENGTH} 球。`)
  for (const [index, pitch] of sequence.entries()) {
    const prefix = `第 ${index + 1} 球：`
    if (terminal) return failed(`${prefix}前一球已結束打席，請刪除結束後的球。`)
    if (!pitchTypes.includes(pitch.pitch_type)) return failed(`${prefix}球種不在目前模型支援名單中。`)
    if (pitch.zone !== null && (!Number.isInteger(pitch.zone) || pitch.zone < 0 || pitch.zone > 12)) return failed(`${prefix}落點須為未知或 0–12 分區。`)
    if (pitch.velocity !== null && (!Number.isFinite(pitch.velocity) || pitch.velocity < 40 || pitch.velocity > 180)) return failed(`${prefix}球速須為空白或 40–180 km/h。`)
    if (!PITCH_RESULTS.includes(pitch.result)) return failed(`${prefix}請選擇支援的投球結果。`)
    if (pitch.result === 'ball') balls += 1
    else if (pitch.result === 'foul') strikes = Math.min(2, strikes + 1)
    else if (pitch.result !== 'in_play') strikes += 1
    terminal = balls >= 4 || strikes >= 3 || pitch.result === 'in_play'
  }
  return { balls, strikes, terminal, error: null }
}

export function sequenceIssue(sequence: SequencePitch[], pitchTypes: string[], balls: number, strikes: number): string | null {
  if (!sequence.length) return null
  const state = reconstructSequence(sequence, pitchTypes)
  if (state.error) return state.error
  if (state.terminal) return '這段序列已結束打席（四壞、三振或球進場內），沒有下一球可預測。請開始新打席或修正序列。'
  if (state.balls !== balls || state.strikes !== strikes) return `球數與序列不一致：完整歷程應為 ${state.balls} 壞 ${state.strikes} 好。請同步球數或修正序列。`
  return null
}
