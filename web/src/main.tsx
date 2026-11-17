import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MAX_SEQUENCE_LENGTH, PITCH_RESULTS, reconstructSequence, sequenceIssue } from './sequence'
import type { SequencePitch } from './sequence'
import { fetchJson } from './network'
import { validateDemo } from './demo'
import type { DemoBundle } from './demo'
import './style.css'
import './week2.css'
import './week3.css'

type Player = { id: string; name: string; role: 'pitcher' | 'batter'; hand: string | null; sample_count: number }
type Task = 'pitch' | 'zone' | 'result'
type Capabilities = { sequence?: boolean; batter_conditioned_model?: boolean; conformal?: boolean; conditional_result?: boolean }
type Metrics = { n: number; log_loss: number; top1_accuracy: number; top2_accuracy: number; ece: number }
type Audit = { n: number; coverage: number; mean_set_size: number; ece_before: number; ece_after: number; log_loss_before: number; log_loss_after: number }
type Calibration = {
  method?: string; target_coverage?: number; temperature?: Partial<Record<Task, number>>
  audit?: Partial<Record<Task, Audit>>; limitations?: string | string[]
  split?: Record<string, { date_min: string; date_max: string; rows: number }>
}
type ModelInfo = {
  selected_candidate?: string; selection_rule?: string; selection_reason?: string
  training_rows?: number; test_evaluated?: boolean
  validation?: Record<string, Partial<Record<Task, Metrics>>>
  calibration_audit?: Partial<Record<Task, Audit>>
}
type ModelSummary = { model_version: string; model_name?: string; data_version: string; data_cutoff: string; capabilities?: Capabilities; model_info?: ModelInfo | null; calibration?: Calibration | null }
type Recommendation = { pitch_type: string; zone: number; expected_run_change: number; direct_sample_count: number; pooled_sample_count: number; support: string; method?: string }
type Prediction = ModelSummary & {
  pitch_probabilities: { pitch_type: string; name: string; probability: number }[]
  zone_probabilities: { zone: number; name: string; probability: number }[]
  result_probabilities?: { result: string; probability: number }[]
  recommendations: Recommendation[]; sample_counts: Record<string, number>; warnings: string[]
  prediction_sets?: Partial<Record<Task, { labels: (string | number)[]; target_coverage: number; threshold: number | null }>> | null
  history_summary?: { provided: boolean; length: number; balls: number | null; strikes: number | null; missing_zone_count: number; missing_velocity_count: number; sequence_used?: boolean }
  sequence_used?: boolean; source_mode: string; elapsed_ms: number
}
type Metadata = ModelSummary & {
  games: number | null; pitches: number | null; training_pitches: number; pitch_types?: string[]
  by_year: { year: number; games: number; pitches: number; coordinate_missing_rate: number; velocity_missing_rate: number }[]
  sequence_schema?: { max_length: number; complete_current_pa: boolean }
}
type FinalMetrics = Metrics & { coverage?: number; mean_set_size?: number }
type EvaluationScope = { selected: Partial<Record<Task, FinalMetrics>>; baselines?: Record<string, Partial<Record<Task, FinalMetrics>>> }
type Evaluation = EvaluationScope & {
  frozen_bundle: { model_version: string; sha256: string; data_cutoff: string }
  period: { start: string; end: string }; test_evaluated: boolean
  catalog_serving?: EvaluationScope
  limitations?: string[]
}
type FixedCases = DemoBundle<Prediction> & { metadata?: Metadata; model_info?: ModelSummary; players?: Player[]; evaluation?: Evaluation }
const ENV = (import.meta as ImportMeta & { env: Record<string, string> }).env
const BASE = ENV.VITE_API_BASE_URL?.replace(/\/$/, '') || (ENV.DEV ? '/api' : '')
const pitchNames: Record<string, string> = { FF: '四縫線', SI: '伸卡／二縫線', FC: '卡特', SL: '滑球', CU: '曲球', CH: '變速球', FO: '指叉球', FS: '快速指叉球', KN: '蝴蝶球', EP: '小便球' }
const resultNames: Record<string, string> = { ball: '壞球', called_strike: '看球好球', swinging_strike: '揮空', foul: '界外球', in_play: '球進場內', hit_by_pitch: '觸身球', other: '其他結果' }
const taskNames: Record<Task, string> = { pitch: '球種', zone: '落點', result: '投球結果' }
const candidateNames: Record<string, string> = { league_count: '聯盟球數頻率', pitcher_count_shrunk: '投手球數頻率（收縮）', lightgbm_context: 'LightGBM 情境', lightgbm_history: 'LightGBM 情境＋歷程', gru: 'GRU 序列' }
const zones = ['左上', '中上', '右上', '左中', '正中', '右中', '左下', '中下', '右下', '框外上方', '框外右側', '框外下方', '框外左側']
const tasks: Task[] = ['pitch', 'zone', 'result']
const percent = (n: number | undefined | null) => n == null || !Number.isFinite(n) ? '—' : `${(n * 100).toFixed(1)}%`
const integer = (n: number | undefined | null) => n == null || !Number.isFinite(n) ? '—' : new Intl.NumberFormat('zh-TW').format(n)
const decimal = (n: number | undefined | null, places = 3) => n == null || !Number.isFinite(n) ? '—' : n.toFixed(places)
const labelFor = (task: Task, label: string | number) => task === 'zone' ? `Z${Number(label) + 1} ${zones[Number(label)] || label}` : task === 'pitch' ? pitchNames[label] || String(label) : resultNames[label] || String(label)

const read = <T,>(url: string, options?: RequestInit) => fetchJson<T>(BASE + url, options)

function Logo() {
  return <svg viewBox="0 0 44 44" width="38" aria-hidden="true"><circle cx="22" cy="22" r="20" fill="#c9df94" /><path d="M8 8c13 6 13 22 0 28M36 8c-13 6-13 22 0 28" stroke="#1c3d32" strokeWidth="1.7" fill="none" /><path d="m12 13 5-3m-2 10 5-1m-6 8 5 1m-7 5 5 3m15-23-5-3m2 10-5-1m6 8-5 1m7 5-5 3" stroke="#1c3d32" strokeWidth="1.2" /></svg>
}

function ModelEvidence({ summary, pending }: { summary: ModelSummary | null; pending: boolean }) {
  const [metricTask, setMetricTask] = useState<Task>('pitch')
  const info = summary?.model_info
  const calibration = summary?.calibration
  const audit = calibration?.audit || info?.calibration_audit
  const candidates = Object.entries(info?.validation || {})
  return <>
    <details className="analysis-details">
      <summary>模型比較</summary>
      <div className="details-content">
        {pending ? <p className="subtle">正在讀取模型比較。</p> : !info ? <p className="muted-message">此版本尚未提供模型比較。</p> : <>
          <div className="model-decision">
            <span className="chip">目前採用</span>
            <strong>{candidateNames[info.selected_candidate || ''] || info.selected_candidate || summary?.model_name || summary?.model_version}</strong>
            <p>{info.selection_reason || '此版本尚未提供模型採用說明。'}</p>
            {info.selection_rule && <small>{info.selection_rule}</small>}
          </div>
          {candidates.length > 0 && <>
            <div className="metric-tabs" role="group" aria-label="模型比較任務">
              {tasks.map(task => <button key={task} aria-pressed={metricTask === task} onClick={() => setMetricTask(task)}>{taskNames[task]}</button>)}
            </div>
            <p className="table-hint">可左右滑動查看完整表格。</p>
            <div className="table-wrap" tabIndex={0} role="region" aria-label="模型比較表">
              <table className="metric-table comparison-table">
                <caption>{taskNames[metricTask]}驗證指標。各模型使用相同的驗證資料，log loss、ECE 越低越好，命中率越高越好。</caption>
                <thead><tr><th>模型</th><th>樣本數</th><th>Log loss</th><th>Top-1</th><th>Top-2</th><th>ECE</th></tr></thead>
                <tbody>{candidates.map(([name, metrics]) => {
                  const m = metrics[metricTask]
                  if (!m) return null
                  return <tr key={name} className={name === info.selected_candidate ? 'selected-model' : ''}>
                    <td><b>{candidateNames[name] || name}</b><span>{name}</span></td>
                    <td>{integer(m.n)}</td><td>{decimal(m.log_loss)}</td><td>{percent(m.top1_accuracy)}</td>
                    <td>{percent(m.top2_accuracy)}</td><td>{decimal(m.ece)}</td>
                  </tr>
                })}</tbody>
              </table>
            </div>
          </>}
          <p className="chart-note">訓練樣本 {integer(info.training_rows)} 筆。{info.test_evaluated === false ? '此模型於最終測試前凍結，測試結果請見下方報告。' : info.test_evaluated === true ? '此版本的最終測試結果請見下方報告。' : '最終測試狀態未提供。'}</p>
        </>}
      </div>
    </details>
    <details className="analysis-details">
      <summary>校準稽核</summary>
      <div className="details-content">
        {pending ? <p className="subtle">正在讀取校準稽核。</p> : !summary?.capabilities?.conformal || !audit ? <p className="muted-message">此版本尚未提供校準稽核與預測集合。</p> : <>
          <p className="subtle">目標覆蓋率 {percent(calibration?.target_coverage)}。實測覆蓋率與平均集合大小來自獨立保留的稽核資料，實際覆蓋率可能隨時間下降。</p>
          <p className="table-hint">可左右滑動查看完整表格。</p>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="校準稽核表">
            <table className="metric-table audit-table">
              <thead><tr><th>任務</th><th>稽核樣本</th><th>實測覆蓋率</th><th>平均集合大小</th><th>ECE 校準前 → 後</th></tr></thead>
              <tbody>{tasks.map(task => {
                const m = audit[task]
                if (!m) return null
                return <tr key={task}>
                  <td>{taskNames[task]}</td><td>{integer(m.n)}</td><td>{percent(m.coverage)}</td>
                  <td>{decimal(m.mean_set_size, 2)}</td><td>{decimal(m.ece_before)} → {decimal(m.ece_after)}</td>
                </tr>
              })}</tbody>
            </table>
          </div>
          {calibration?.split && <div className="split-summary">{Object.entries(calibration.split).map(([name, split]) => <span key={name}><b>{({ temperature: '溫度校準', conformal: '集合門檻', audit: '保留稽核' } as Record<string, string>)[name] || name}</b>{split.date_min}～{split.date_max} · {integer(split.rows)} 筆</span>)}</div>}
          {calibration?.limitations && <p className="chart-note">{Array.isArray(calibration.limitations) ? calibration.limitations.join('。') : calibration.limitations}</p>}
        </>}
      </div>
    </details>
  </>
}

function FinalEvaluation({ evaluation, unavailable }: { evaluation: Evaluation | null; unavailable: boolean }) {
  const [scope, setScope] = useState<'all' | 'catalog'>('all')
  const [task, setTask] = useState<Task>('pitch')
  const showCatalog = scope === 'catalog' && !!evaluation?.catalog_serving
  const selectedScope = showCatalog ? evaluation?.catalog_serving : evaluation
  const selected = selectedScope?.selected
  const comparison = [['lightgbm_history', selectedScope?.selected], ...Object.entries(selectedScope?.baselines || {})] as [string, Partial<Record<Task, FinalMetrics>> | undefined][]
  const pitcherBaseline = selectedScope?.baselines?.pitcher_count_shrunk?.pitch
  return <details className="analysis-details final-evaluation">
    <summary>2025 年最終測試</summary>
    <div className="details-content">
      {!evaluation?.test_evaluated ? <p className="muted-message">{unavailable || evaluation ? '目前尚未取得可用的最終測試報告。' : '正在讀取最終測試報告。'}</p> : <>
        <p className="subtle">測試期間 {evaluation.period.start}～{evaluation.period.end}。測試資料在訓練、調參、模型選擇與校準完成後才使用。</p>
        {evaluation.catalog_serving && <>
          <div className="metric-tabs" role="group" aria-label="最終測試樣本範圍">
            <button aria-pressed={!showCatalog} onClick={() => setScope('all')}>全部合格投球</button>
            <button aria-pressed={showCatalog} onClick={() => setScope('catalog')}>網站可選投打</button>
          </div>
          <p className="chart-note">全體評估包含模型未見過的球員。網站子集只包含可在網站選取的投手與打者。</p>
        </>}
        <p className="table-hint">可左右滑動查看完整表格。</p>
        <div className="table-wrap" tabIndex={0} role="region" aria-label="最終測試指標表">
          <table className="metric-table final-table">
            <caption>{showCatalog ? '網站可選投打子集' : '全部合格投球'} · 凍結模型</caption>
            <thead><tr><th>任務</th><th>樣本數</th><th>Log loss</th><th>Top-1</th><th>Top-2</th><th>ECE</th><th>實測覆蓋率</th><th>集合大小</th></tr></thead>
            <tbody>{tasks.map(task => {
              const m = selected?.[task]
              if (!m) return null
              return <tr key={task}>
                <td>{taskNames[task]}</td><td>{integer(m.n)}</td><td>{decimal(m.log_loss)}</td><td>{percent(m.top1_accuracy)}</td>
                <td>{percent(m.top2_accuracy)}</td><td>{decimal(m.ece)}</td><td>{percent(m.coverage)}</td><td>{decimal(m.mean_set_size, 2)}</td>
              </tr>
            })}</tbody>
          </table>
        </div>
        {selectedScope?.baselines && <>
          <div className="metric-tabs" role="group" aria-label="最終測試比較任務">
            {tasks.map(value => <button key={value} aria-pressed={task === value} onClick={() => setTask(value)}>{taskNames[value]}</button>)}
          </div>
          <div className="table-wrap" tabIndex={0} role="region" aria-label="最終測試基準比較表">
            <table className="metric-table comparison-table">
              <caption>各模型使用相同的最終測試樣本，log loss 越低越好。</caption>
              <thead><tr><th>模型</th><th>樣本數</th><th>Log loss</th><th>Top-1</th><th>Top-2</th><th>ECE</th></tr></thead>
              <tbody>{comparison.map(([name, values]) => {
                const m = values?.[task]
                if (!m) return null
                return <tr key={name}>
                  <td>{candidateNames[name] || name}</td><td>{integer(m.n)}</td><td>{decimal(m.log_loss)}</td>
                  <td>{percent(m.top1_accuracy)}</td><td>{percent(m.top2_accuracy)}</td><td>{decimal(m.ece)}</td>
                </tr>
              })}</tbody>
            </table>
          </div>
        </>}
        {selected?.pitch && pitcherBaseline && <p className="muted-message">
          此範圍球種 log loss，凍結模型為 {decimal(selected.pitch.log_loss)}，投手收縮頻率為 {decimal(pitcherBaseline.log_loss)}。
          {selected.pitch.log_loss >= pitcherBaseline.log_loss ? '投手收縮頻率基準在此項指標相同或較佳。' : '凍結模型在此項指標較佳。'}
        </p>}
        <details>
          <summary>測試版本與限制</summary>
          <p>模型版本 {evaluation.frozen_bundle.model_version}<br />SHA-256 <code>{evaluation.frozen_bundle.sha256}</code></p>
          {!!evaluation.limitations?.length && <ul>{evaluation.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>}
        </details>
      </>}
    </div>
  </details>
}

function App() {
  const [players, setPlayers] = useState<Player[]>([])
  const [metadata, setMetadata] = useState<Metadata | null>(null)
  const [modelSummary, setModelSummary] = useState<ModelSummary | null>(null)
  const [modelInfoPending, setModelInfoPending] = useState(true)
  const [modelInfoError, setModelInfoError] = useState('')
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null), [evaluationUnavailable, setEvaluationUnavailable] = useState(false)
  const [mode, setMode] = useState<'realtime' | 'fixed'>('realtime')
  const [fixedCases, setFixedCases] = useState<FixedCases | null>(null), [caseId, setCaseId] = useState('')
  const [fixedLoading, setFixedLoading] = useState(false), [fixedError, setFixedError] = useState(''), [waitingLong, setWaitingLong] = useState(false)
  const [pitcher, setPitcher] = useState(''), [batter, setBatter] = useState('')
  const [balls, setBalls] = useState(0), [strikes, setStrikes] = useState(0), [outs, setOuts] = useState(0)
  const [bases, setBases] = useState([false, false, false])
  const [sequence, setSequence] = useState<SequencePitch[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const historySummaryRef = useRef<HTMLElement>(null)
  const [prediction, setPrediction] = useState<Prediction | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [startup, setStartup] = useState(true)
  const [retry, setRetry] = useState(0), [tab, setTab] = useState<'analysis' | 'about'>('analysis')
  const pitchTypes = metadata?.pitch_types || []
  const reconstructed = useMemo(() => reconstructSequence(sequence, pitchTypes), [sequence, pitchTypes])
  const currentBalls = mode === 'realtime' && sequence.length ? reconstructed.balls : balls
  const currentStrikes = mode === 'realtime' && sequence.length ? reconstructed.strikes : strikes
  const historyError = sequenceIssue(sequence, pitchTypes, currentBalls, currentStrikes)
  const capabilities = prediction?.capabilities || modelSummary?.capabilities || metadata?.capabilities
  const unsupportedHistory = sequence.length > 0 && !capabilities?.sequence ? '目前服務不支援打席歷程，請清空歷程後再分析。' : null
  const inputIssue = historyError || unsupportedHistory
  useEffect(() => {
    if (mode === 'realtime' && inputIssue) setHistoryOpen(true)
  }, [inputIssue, mode])
  useEffect(() => {
    const controller = new AbortController()
    if (mode === 'fixed') { setStartup(false); setModelInfoPending(false); return () => controller.abort() }
    setStartup(true); setError(''); setModelInfoPending(true); setModelInfoError('')
    setEvaluation(null); setEvaluationUnavailable(false)
    if (!BASE && !ENV.DEV) { setError('即時分析服務尚未設定，可先使用示範案例。'); setStartup(false); setModelInfoPending(false); setEvaluationUnavailable(true); return }
    Promise.all([read<{ players: Player[] }>('/players', { signal: controller.signal }), read<Metadata>('/metadata', { signal: controller.signal })])
      .then(([catalog, meta]) => { if (!controller.signal.aborted) { setPlayers(catalog.players); setMetadata(meta); setPitcher(p => p || catalog.players.find(x => x.role === 'pitcher')?.id || ''); setBatter(p => p || catalog.players.find(x => x.role === 'batter')?.id || '') } })
      .catch(e => { if (!controller.signal.aborted) setError(e.message) })
      .finally(() => { if (!controller.signal.aborted) setStartup(false) })
    read<ModelSummary>('/model-info', { signal: controller.signal }).then(info => { if (!controller.signal.aborted) setModelSummary(info) })
      .catch(() => { if (!controller.signal.aborted) setModelInfoError('模型摘要尚未取得；可用的推論功能仍會正常顯示。') })
      .finally(() => { if (!controller.signal.aborted) setModelInfoPending(false) })
    read<Evaluation>('/evaluation', { signal: controller.signal }).then(info => { if (!controller.signal.aborted) setEvaluation(info) })
      .catch(() => { if (!controller.signal.aborted) setEvaluationUnavailable(true) })
    return () => controller.abort()
  }, [retry, mode])
  useEffect(() => {
    if (mode !== 'fixed') return
    const controller = new AbortController()
    setFixedLoading(true); setFixedError(''); setPrediction(null); setMetadata(null); setModelSummary(null); setEvaluation(null)
    fetchJson<unknown>(`${ENV.BASE_URL || './'}demo/cases.json`, { signal: controller.signal }, 10000)
      .then(value => { if (!controller.signal.aborted) { const bundle = validateDemo<Prediction>(value) as FixedCases; setFixedCases(bundle); setCaseId(bundle.cases[0].id) } })
      .catch(e => { if (!controller.signal.aborted) setFixedError(e.message) })
      .finally(() => { if (!controller.signal.aborted) setFixedLoading(false) })
    return () => controller.abort()
  }, [mode, retry])
  useEffect(() => {
    if (mode !== 'fixed' || !fixedCases) return
    const selected = fixedCases.cases.find(item => item.id === caseId)
    if (!selected) return
    const request = selected.request
    setPitcher(request.pitcher_id); setBatter(request.batter_id)
    setBalls(request.state.balls); setStrikes(request.state.strikes); setOuts(request.state.outs); setBases(request.state.bases)
    setSequence(request.sequence); setPrediction(selected.response); setBusy(false); setError('')
    setMetadata(fixedCases.metadata || null); setModelSummary(fixedCases.model_info || selected.response)
    setEvaluation(fixedCases.evaluation || null); setEvaluationUnavailable(!fixedCases.evaluation)
    setPlayers(fixedCases.players || fixedCases.cases.flatMap(item => [
      { id: item.request.pitcher_id, name: item.pitcher_name || item.request.pitcher_id, role: 'pitcher' as const, hand: null, sample_count: 0 },
      { id: item.request.batter_id, name: item.batter_name || item.request.batter_id, role: 'batter' as const, hand: null, sample_count: 0 },
    ]).filter((item, index, array) => array.findIndex(p => p.id === item.id && p.role === item.role) === index))
  }, [mode, fixedCases, caseId])
  useEffect(() => {
    const controller = new AbortController()
    if (mode === 'fixed') return () => controller.abort()
    setPrediction(null); setBusy(false)
    if (!pitcher || !batter || startup || inputIssue) return () => controller.abort()
    setBusy(true); setError('')
    const timer = setTimeout(() => {
      read<Prediction>('/predict', { method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: controller.signal,
        body: JSON.stringify({ pitcher_id: pitcher, batter_id: batter, state: { balls: currentBalls, strikes: currentStrikes, outs, bases }, sequence }) })
        .then(result => { if (!controller.signal.aborted) setPrediction(result) })
        .catch(e => { if (!controller.signal.aborted) setError(e.message) })
        .finally(() => { if (!controller.signal.aborted) setBusy(false) })
    }, 250)
    return () => { clearTimeout(timer); controller.abort() }
  }, [pitcher, batter, currentBalls, currentStrikes, outs, bases, sequence, retry, startup, inputIssue, mode])
  useEffect(() => {
    setWaitingLong(false)
    if (mode === 'fixed' || !(startup || busy)) return
    const timer = setTimeout(() => setWaitingLong(true), 20000)
    return () => clearTimeout(timer)
  }, [startup, busy, mode])
  function changeMode(next: 'realtime' | 'fixed') {
    if (mode === next) return
    setPrediction(null); setError(''); setBusy(false); setSequence([]); setHistoryOpen(false)
    setPitcher(''); setBatter(''); setPlayers([]); setFixedCases(null); setCaseId('')
    setMetadata(null); setModelSummary(null); setEvaluation(null)
    setFixedError(''); setFixedLoading(next === 'fixed'); setStartup(next === 'realtime')
    setMode(next)
  }
  const invalidate = () => setPrediction(null)
  function resetHistory() { invalidate(); setSequence([]); setBalls(0); setStrikes(0) }
  function changePlayer(role: 'pitcher' | 'batter', id: string) {
    if (id === (role === 'pitcher' ? pitcher : batter)) return
    resetHistory()
    if (role === 'pitcher') setPitcher(id)
    else setBatter(id)
  }
  function editPitch(index: number, updates: Partial<SequencePitch>) { invalidate(); setSequence(items => items.map((item, i) => i === index ? { ...item, ...updates } : item)) }
  const pitching = players.find(p => p.id === pitcher && p.role === 'pitcher')
  const batting = players.find(p => p.id === batter && p.role === 'batter')
  const sorted = prediction ? [...prediction.pitch_probabilities].sort((a, b) => b.probability - a.probability) : []
  const maxZone = Math.max(.001, ...(prediction?.zone_probabilities.map(z => z.probability) || []))
  const isFixed = mode === 'fixed'
  const updating = isFixed ? fixedLoading : startup || busy
  const analysisError = isFixed ? fixedError : error
  const currentIssue = isFixed ? null : inputIssue
  const currentPrediction = updating || analysisError || currentIssue ? null : prediction
  const recommendations = currentPrediction?.recommendations.slice(0, 3) || []
  const summary = prediction || modelSummary || metadata
  const dataCutoff = summary?.data_cutoff
  const matchupSamples = currentPrediction?.sample_counts.matchup
  const history = currentPrediction?.history_summary
  const selectedCase = fixedCases?.cases.find(item => item.id === caseId)
  const runners = bases.map((occupied, i) => occupied ? `${i + 1} 壘` : '').filter(Boolean)
  const baseStatus = runners.length ? runners.join('、') + '有人' : '壘上無人'
  const sequenceLimit = Math.min(metadata?.sequence_schema?.max_length || MAX_SEQUENCE_LENGTH, MAX_SEQUENCE_LENGTH)
  const canAddPitch = !isFixed && !startup && capabilities?.sequence && pitchTypes.length > 0
    && sequence.length < sequenceLimit && !reconstructed.terminal && !currentIssue

  function addPitch() {
    if (!canAddPitch) return
    invalidate()
    setHistoryOpen(true)
    setSequence(items => [...items, { pitch_type: pitchTypes[0], zone: null, velocity: null, result: 'ball' }])
  }

  function retryAnalysis() {
    invalidate()
    setRetry(n => n + 1)
  }

  return <>
    <header className="header">
      <div className="brand"><Logo /><div><strong>球路參謀</strong><span>PITCHADVISOR TW</span></div></div>
      <nav aria-label="主選單">
        <button className={tab === 'analysis' ? 'active' : ''} aria-current={tab === 'analysis' ? 'page' : undefined} onClick={() => setTab('analysis')}>配球分析</button>
        <button className={tab === 'about' ? 'active' : ''} aria-current={tab === 'about' ? 'page' : undefined} onClick={() => setTab('about')}>資料與方法</button>
      </nav>
    </header>
    <main>
      {tab === 'about' ? <>
        <div className="page-intro"><h1>資料與方法</h1></div>
        <section className="about panel">
          <p>球路參謀使用 Rebas Open Data 的中職逐球資料。配球候選依歷史資料估計的失分變化排序。</p>
          <dl className="about-overview">
            <div><dt>比賽場數</dt><dd>{integer(metadata?.games)}</dd></div>
            <div><dt>逐球事件</dt><dd>{integer(metadata?.pitches)}</dd></div>
            <div><dt>訓練資料截止</dt><dd>{dataCutoff || '—'}</dd></div>
          </dl>
          <ModelEvidence summary={summary} pending={modelInfoPending} />
          <FinalEvaluation evaluation={evaluation} unavailable={evaluationUnavailable} />
          {modelInfoError && <p className="muted-message">{modelInfoError}</p>}
          <details className="analysis-details">
            <summary>年度資料與來源</summary>
            <div className="details-content">
              {metadata?.by_year.length ? <div className="table-wrap">
                <table>
                  <thead><tr><th>年度</th><th>場數</th><th>逐球事件</th><th>座標缺值</th><th>球速缺值</th></tr></thead>
                  <tbody>{metadata.by_year.map(y => <tr key={y.year}><td>{y.year}</td><td>{integer(y.games)}</td><td>{integer(y.pitches)}</td><td>{percent(y.coordinate_missing_rate)}</td><td>{percent(y.velocity_missing_rate)}</td></tr>)}</tbody>
                </table>
              </div> : <p>{updating ? '正在載入資料。' : '目前無法取得年度資料。'}</p>}
              <p className="source-links">
                <a href="https://blog.rebas.tw/articles/4136" target="_blank" rel="noreferrer">野革盃官方公告</a>
                <a href="https://github.com/rebas-tw/rebas.tw-open-data" target="_blank" rel="noreferrer">Rebas Open Data（ODC-By）</a>
              </p>
            </div>
          </details>
        </section>
      </> : <>
        <div className="page-intro">
          <div><h1>配球分析</h1><p>選擇投手、打者與目前情境，比較下一球的配球建議。</p></div>
          <div className="mode-buttons" role="group" aria-label="分析模式">
            <button aria-pressed={!isFixed} onClick={() => changeMode('realtime')}>即時分析</button>
            <button aria-pressed={isFixed} onClick={() => changeMode('fixed')}>示範案例</button>
          </div>
        </div>
        {isFixed && <section className="mode-panel" aria-label="示範案例">
          <div className="fixed-case-picker">
            <label htmlFor="fixed-case">示範案例</label>
            <select id="fixed-case" value={caseId} disabled={!fixedCases} onChange={e => {
              if (e.target.value === caseId) return
              invalidate()
              setCaseId(e.target.value)
            }}>
              {!fixedCases && <option value="">選擇示範案例</option>}
              {fixedCases?.cases.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}
            </select>
            <span className="fixed-mode-note">預先計算・不可編輯</span>
          </div>
        </section>}

        <div className="workspace">
          <aside className="panel controls">
            <h2 id="matchup-settings">對戰情境</h2>
            <fieldset className="control-fields" aria-labelledby="matchup-settings" disabled={isFixed || startup || !players.length}>
              <label htmlFor="pitcher">投手 {pitching?.hand && <span>{pitching.hand === 'L' ? '左投' : pitching.hand === 'R' ? '右投' : ''}</span>}</label>
              <select id="pitcher" value={pitcher} onChange={e => changePlayer('pitcher', e.target.value)}>
                <option value="" disabled>選擇投手</option>
                {players.filter(p => p.role === 'pitcher').map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <label className="small-label" htmlFor="batter">打者 {batting?.hand && <span>{batting.hand === 'L' ? '左打' : batting.hand === 'R' ? '右打' : ''}</span>}</label>
              <select id="batter" value={batter} onChange={e => changePlayer('batter', e.target.value)}>
                <option value="" disabled>選擇打者</option>
                {players.filter(p => p.role === 'batter').map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              {sequence.length > 0 && <p className="control-hint">球數依打席歷程計算。切換球員會開始新打席。</p>}
              <div className="separator" />
              <div className="small-label" id="balls-label">壞球</div>
              <div className="segments" role="group" aria-labelledby="balls-label">
                {[0, 1, 2, 3].map(n => <button key={n} disabled={sequence.length > 0} aria-label={`${n} 壞球`} aria-pressed={currentBalls === n} className={currentBalls === n ? 'selected' : ''} onClick={() => { if (n !== balls) { invalidate(); setBalls(n) } }}>{n}</button>)}
              </div>
              <div className="small-label" id="strikes-label">好球</div>
              <div className="segments" role="group" aria-labelledby="strikes-label">
                {[0, 1, 2].map(n => <button key={n} disabled={sequence.length > 0} aria-label={`${n} 好球`} aria-pressed={currentStrikes === n} className={currentStrikes === n ? 'selected' : ''} onClick={() => { if (n !== strikes) { invalidate(); setStrikes(n) } }}>{n}</button>)}
              </div>
              <div className="small-label" id="outs-label">出局數</div>
              <div className="segments" role="group" aria-labelledby="outs-label">
                {[0, 1, 2].map(n => <button key={n} aria-label={`${n} 出局`} aria-pressed={outs === n} className={outs === n ? 'selected' : ''} onClick={() => { if (n !== outs) { invalidate(); setOuts(n) } }}>{n}</button>)}
              </div>
              <div className="small-label" id="bases-label">壘包</div>
              <div className="bases" role="group" aria-labelledby="bases-label">
                {[1, 0, 2].map(i => <button key={i} className={`base base-${i} ${bases[i] ? 'occupied' : ''}`} aria-label={`${i + 1} 壘${bases[i] ? '有人' : '無人'}`} aria-pressed={bases[i]} onClick={() => { invalidate(); setBases(b => b.map((x, j) => j === i ? !x : x)) }}><span>{i + 1}B</span></button>)}
                <span className="home-plate" />
              </div>
            </fieldset>
          </aside>

          <div className="results">
            <div className="result-heading">
              <div>
                <h2>{pitching?.name || '投手'} <small>對</small> {batting?.name || '打者'}</h2>
                <p className="matchup-context">{currentBalls} 壞 {currentStrikes} 好 · {outs} 出局 · {baseStatus}</p>
              </div>
              {dataCutoff && <span className="training-cutoff">訓練資料截止 {dataCutoff}</span>}
            </div>
            <section className="panel recommendations" aria-labelledby="recommendation-heading">
              <div className="card-heading"><h3 id="recommendation-heading">配球建議</h3><span>落點採投手視角</span></div>
              {analysisError ? <div className="error result-status" role="alert">
                <div><b>{isFixed ? '無法載入示範案例' : '暫時無法分析'}</b><p>{analysisError}</p></div>
                <button onClick={retryAnalysis}>{isFixed ? '重新載入' : '重新連線'}</button>
              </div> : currentIssue ? <p className="result-status" role="status">
                {reconstructed.terminal ? '這個打席已結束。清空歷程可開始新打席。' : '請修正打席歷程後再分析。'}
              </p> : !currentPrediction ? <p className="result-status" role="status">
                {waitingLong && updating ? '分析服務仍在啟動，等候時可切換至示範案例。'
                  : isFixed ? '正在載入示範案例…' : startup ? '正在載入球員名單…'
                  : pitcher && batter ? '正在分析…' : '選擇投手與打者後開始分析。'}
              </p> : <>
                {recommendations.length ? <div className="recommendation-list">
                  {recommendations.map((r, i) => <article key={`${r.pitch_type}-${r.zone}`} className={i === 0 ? 'recommendation best' : 'recommendation'}>
                    <div className="rank">{i === 0 ? '首選' : `候選 ${i + 1}`}</div>
                    <h4>{pitchNames[r.pitch_type] || r.pitch_type}</h4>
                    <p>{zones[r.zone]}</p>
                    <span className="support">{r.support === 'pooled' ? '參考聯盟樣本' : '投手樣本支持'}</span>
                  </article>)}
                </div> : <p className="result-status">目前沒有足夠資料提供候選。</p>}
                {typeof matchupSamples === 'number' && matchupSamples < 30 && <p className="sample-warning">直接對戰樣本偏少（{integer(matchupSamples)} 球）。</p>}
                <p className="recommendation-note">依歷史資料估計，請配合實際狀況判斷。</p>
                {recommendations.length > 0 && <details className="analysis-details">
                  <summary>查看配球依據</summary>
                  <div className="details-content">
                    <p>估計失分變化越低，排序越前。各候選的樣本數以訓練資料計算。</p>
                    <div className="table-wrap" tabIndex={0} aria-label="配球依據表格">
                      <table>
                        <thead><tr><th scope="col">候選</th><th scope="col">球種／落點</th><th scope="col">估計失分變化</th><th scope="col">投手相同球數</th><th scope="col">聯盟同球種與落點</th></tr></thead>
                        <tbody>{recommendations.map((r, i) => <tr key={`${r.pitch_type}-${r.zone}`}>
                          <th scope="row">{i + 1}</th>
                          <td>{pitchNames[r.pitch_type] || r.pitch_type} {zones[r.zone]} <code>{r.pitch_type} / Z{r.zone + 1}</code></td>
                          <td>{r.expected_run_change > 0 ? '+' : ''}{decimal(r.expected_run_change)}</td>
                          <td>{integer(r.direct_sample_count)} 球</td>
                          <td>{integer(r.pooled_sample_count)} 球</td>
                        </tr>)}</tbody>
                      </table>
                    </div>
                  </div>
                </details>}
              </>}
            </section>

            <div className="history-toolbar">
              <details className="panel sequence-editor" open={historyOpen} onToggle={e => setHistoryOpen(e.currentTarget.open)}>
                <summary ref={historySummaryRef}>
                  <span>{isFixed ? '打席歷程' : '打席歷程（選填）'}</span>
                  <span className="history-count">{sequence.length} 球{currentIssue ? ' · 需確認' : ''}</span>
                </summary>
                <div className="details-content">
                  <fieldset className="control-fields" disabled={isFixed || startup}>
                    {isFixed ? (!sequence.length && <p>此案例無打席歷程。</p>) : <>
                      <p className="subtle">從打席第一球依序輸入，球數會自動計算。落點與球速可留空。</p>
                      {!startup && !capabilities?.sequence && <p className="muted-message">目前服務不支援打席歷程，可直接設定球數分析。</p>}
                    </>}
                    {sequence.length > 0 && <ol className="history-list">{sequence.map((pitch, i) => <li key={i} className="history-pitch">
                      <div className="history-pitch-heading"><b>第 {i + 1} 球</b>{!isFixed && <button className="text-button delete-pitch" aria-label={`刪除第 ${i + 1} 球`} onClick={() => { invalidate(); setSequence(items => items.filter((_, index) => index !== i)) }}>刪除</button>}</div>
                      <div className="history-fields">
                        <label>球種<select aria-label={`第 ${i + 1} 球球種`} value={pitch.pitch_type} onChange={e => editPitch(i, { pitch_type: e.target.value })}>
                          {!pitchTypes.includes(pitch.pitch_type) && <option value={pitch.pitch_type}>{pitchNames[pitch.pitch_type] || pitch.pitch_type}</option>}
                          {pitchTypes.map(type => <option key={type} value={type}>{pitchNames[type] || type}</option>)}
                        </select></label>
                        <label>落點<select aria-label={`第 ${i + 1} 球落點`} value={pitch.zone ?? ''} onChange={e => editPitch(i, { zone: e.target.value === '' ? null : Number(e.target.value) })}>
                          <option value="">未知</option>
                          {zones.map((name, zone) => <option key={zone} value={zone}>{name}</option>)}
                        </select></label>
                        <label>球速 km/h<input aria-label={`第 ${i + 1} 球球速`} type="number" min="40" max="180" step="0.1" inputMode="decimal" placeholder="未知" value={pitch.velocity ?? ''} onChange={e => editPitch(i, { velocity: e.target.value === '' ? null : Number(e.target.value) })} /></label>
                        <label>投球結果<select aria-label={`第 ${i + 1} 球投球結果`} value={pitch.result} onChange={e => editPitch(i, { result: e.target.value as SequencePitch['result'] })}>
                          {PITCH_RESULTS.map(result => <option key={result} value={result}>{resultNames[result]}</option>)}
                        </select></label>
                      </div>
                    </li>)}</ol>}
                    {currentIssue && <p className="history-error" role="alert">{currentIssue}</p>}
                    {!isFixed && <div className="history-actions">
                      <button className="primary-button" disabled={!canAddPitch} onClick={addPitch}>新增一球</button>
                      {sequence.length > 0 && <button className="text-button" onClick={resetHistory}>清空歷程</button>}
                      {sequence.length >= sequenceLimit && <span>已達 {sequenceLimit} 球上限</span>}
                    </div>}
                  </fieldset>
                </div>
              </details>
              {!historyOpen && canAddPitch && <button className="primary-button" onClick={() => { historySummaryRef.current?.focus(); addPitch() }}>新增一球</button>}
            </div>

            {currentPrediction && <>
              <div className="charts">
                <section className="panel pitch-chart">
                  <div className="card-heading"><h3>下一球可能的球種</h3></div>
                  <div className="bar-chart">{sorted.filter(p => p.probability > .003).map((p, i) => <div className="bar-row" key={p.pitch_type}>
                    <div><b>{p.name}</b></div>
                    <div className="bar-track" aria-hidden="true"><div className={i === 0 ? 'bar lead' : 'bar'} style={{ width: `${p.probability * 100}%` }} /></div>
                    <strong>{percent(p.probability)}</strong>
                  </div>)}</div>
                </section>
                <section className="panel zone-chart">
                  <div className="card-heading"><h3>下一球可能的落點</h3><span>投手視角</span></div>
                  <div className="heatmap">{currentPrediction.zone_probabilities.map(z => <div key={z.zone} className={`zone z-${z.zone}`} title={`${z.name}：${percent(z.probability)}`} style={{ backgroundColor: `rgba(38, 101, 74, ${.08 + .8 * z.probability / maxZone})`, color: z.probability / maxZone > .55 ? '#fff' : '#304a3c' }}>
                    <b>{percent(z.probability)}</b><span>{z.zone < 9 ? z.zone + 1 : ['上方', '右側', '下方', '左側'][z.zone - 9]}</span>
                  </div>)}</div>
                  <div className="heat-legend"><span>機率較低</span><i /><span>機率較高</span></div>
                  <p className="chart-note">九宮格為好球帶，外圍四格為帶外落點。</p>
                </section>
              </div>

              <details className="panel analysis-details">
                <summary>更多分析</summary>
                <div className="details-content">
                  {!!currentPrediction.result_probabilities?.length && <section className="outcome-panel">
                    <div className="card-heading"><h3>下一球結果機率</h3></div>
                    <div className="outcome-grid">{currentPrediction.result_probabilities.map(result => <div key={result.result}><span>{resultNames[result.result] || result.result}</span><strong>{percent(result.probability)}</strong></div>)}</div>
                  </section>}
                  <section className="confidence">
                    <div className="card-heading"><h3>訓練期樣本</h3></div>
                    <div className="sample-grid">{[['pitcher', '投手逐球'], ['batter', '打者面對投球'], ['matchup', '直接投打對戰'], ['league_state', '聯盟相同情境']].map(([key, label]) => <div key={key}><strong>{integer(currentPrediction.sample_counts[key])}</strong><span>{label}</span></div>)}</div>
                    <div className="history-receipt">
                      <b>{currentPrediction.sequence_used ? '已使用本打席歷程' : '依目前情境分析，未使用打席歷程'}</b>
                      {history && history.length > 0 && <span>{integer(history.length)} 球 · 落點未知 {integer(history.missing_zone_count)} 球 · 球速未知 {integer(history.missing_velocity_count)} 球</span>}
                    </div>
                    <h3 className="prediction-set-heading">下一球預測集合</h3>
                    <p className="subtle">集合越大，代表越難縮小預測範圍。目標覆蓋率用於評估多次預測。</p>
                    {capabilities?.conformal && currentPrediction.prediction_sets ? <div className="prediction-sets">{tasks.map(task => {
                      const set = currentPrediction.prediction_sets?.[task]
                      return <div className="prediction-set" key={task}>
                        <b>{taskNames[task]} <small>目標覆蓋率 {percent(set?.target_coverage)}</small></b>
                        {set && set.threshold != null ? <div className="set-labels">
                          {set.labels.length ? set.labels.map(label => <span key={String(label)}>{labelFor(task, label)}</span>) : <em>本次沒有符合門檻的候選。</em>}
                        </div> : <p>這項預測目前沒有可用的集合門檻。</p>}
                      </div>
                    })}</div> : <p className="muted-message">此版本未提供已校準的預測集合。</p>}
                    {currentPrediction.warnings.length > 0 && <details className="analysis-details">
                      <summary>資料限制</summary>
                      <ul className="details-content">{currentPrediction.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>
                    </details>}
                    <details className="analysis-details">
                      <summary>技術詳情</summary>
                      <div className="details-content">
                        <dl className="result-meta">
                          <div><dt>模型版本</dt><dd>{currentPrediction.model_version}</dd></div>
                          <div><dt>資料版本</dt><dd>{currentPrediction.data_version}</dd></div>
                          <div><dt>資料來源</dt><dd>{isFixed ? '網站附帶的示範案例' : currentPrediction.source_mode === 'supabase_verified_snapshot' ? 'Supabase 版本已核對' : currentPrediction.source_mode === 'local_snapshot' ? '本機模型快照' : '雲端未核對，使用本機快照'}</dd></div>
                          <div><dt>運算時間</dt><dd>{currentPrediction.elapsed_ms} ms</dd></div>
                          {fixedCases?.bundle_sha256 && <div><dt>模型 SHA-256</dt><dd><code>{fixedCases.bundle_sha256}</code></dd></div>}
                          <div><dt>打者條件特徵</dt><dd>{capabilities?.batter_conditioned_model ? '已提供' : '此版本未提供'}</dd></div>
                        </dl>
                        {isFixed && selectedCase?.description && <p>{selectedCase.description}</p>}
                      </div>
                    </details>
                  </section>
                </div>
              </details>
            </>}
          </div>
        </div>
      </>}
      <footer className="page-footer"><p>資料來源 <a href="https://github.com/rebas-tw/rebas.tw-open-data" target="_blank" rel="noreferrer">Rebas Open Data</a>（ODC-By）</p></footer>
    </main>
  </>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
