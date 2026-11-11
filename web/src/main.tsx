import React, { useEffect, useMemo, useState } from 'react'
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
  return <section className="panel evidence">
    <div className="card-heading"><h3>模型比較與採用依據</h3><span>相同時間切分的驗證資料</span></div>
    {pending ? <p className="subtle">正在讀取模型評估摘要。</p> : !info ? <p className="muted-message">目前服務尚未提供第二週模型比較與校準成果；不顯示推測數字。</p> : <>
      <div className="model-decision"><span className="chip">目前採用</span><strong>{candidateNames[info.selected_candidate || ''] || info.selected_candidate || summary?.model_name || summary?.model_version}</strong><p>{info.selection_reason || '此版本尚未提供模型採用說明。'}</p>{info.selection_rule && <small>{info.selection_rule}</small>}</div>
      {candidates.length > 0 && <><div className="metric-tabs" role="group" aria-label="模型比較任務">{tasks.map(task => <button key={task} aria-pressed={metricTask === task} onClick={() => setMetricTask(task)}>{taskNames[task]}</button>)}</div><p className="table-hint">可左右滑動查看完整表格。</p><div className="table-wrap"><table className="metric-table comparison-table"><caption>{taskNames[metricTask]}驗證指標；log loss、ECE 越低越好，命中率越高越好。</caption><thead><tr><th>模型</th><th>樣本數</th><th>Log loss</th><th>Top-1</th><th>Top-2</th><th>ECE</th></tr></thead><tbody>{candidates.filter(([, metrics]) => metrics[metricTask]).map(([name, metrics]) => {
        const m = metrics[metricTask]!
        return <tr key={name} className={name === info.selected_candidate ? 'selected-model' : ''}><td><b>{candidateNames[name] || name}</b><span>{name}</span></td><td>{integer(m.n)}</td><td>{decimal(m.log_loss)}</td><td>{percent(m.top1_accuracy)}</td><td>{percent(m.top2_accuracy)}</td><td>{decimal(m.ece)}</td></tr>
      })}</tbody></table></div></>}
      <p className="chart-note">訓練樣本 {integer(info.training_rows)} 筆。{info.test_evaluated === false ? '此模型訓練快照於最終測試前凍結；最終測試狀態與數字見下方獨立報告。' : info.test_evaluated === true ? '此版本已執行最終測試；此表仍僅呈現驗證集。' : '最終測試狀態未提供。'}</p>
    </>}
    <div className="evidence-divider" /><div className="card-heading"><h3>機率校準與預測集合稽核</h3><span>獨立保留資料的實測結果</span></div>
    {!summary?.capabilities?.conformal || !audit ? <p className="muted-message">此模型版本尚未提供可用的校準稽核與預測集合。</p> : <>
      <p className="subtle">名目覆蓋率 {percent(calibration?.target_coverage)}。實際覆蓋率與平均集合大小由保留稽核集計算，時間改變可能使覆蓋率下降。</p>
      <p className="table-hint">可左右滑動查看完整表格。</p><div className="table-wrap"><table className="metric-table audit-table"><thead><tr><th>任務</th><th>稽核樣本</th><th>實測覆蓋率</th><th>平均集合大小</th><th>ECE 校準前 → 後</th></tr></thead><tbody>{tasks.filter(task => audit[task]).map(task => {
        const m = audit[task]!
        return <tr key={task}><td>{taskNames[task]}</td><td>{integer(m.n)}</td><td>{percent(m.coverage)}</td><td>{decimal(m.mean_set_size, 2)}</td><td>{decimal(m.ece_before)} → {decimal(m.ece_after)}</td></tr>
      })}</tbody></table></div>
      {calibration?.split && <div className="split-summary">{Object.entries(calibration.split).map(([name, split]) => <span key={name}><b>{({ temperature: '溫度校準', conformal: '集合門檻', audit: '保留稽核' } as Record<string, string>)[name] || name}</b>{split.date_min}～{split.date_max} · {integer(split.rows)} 筆</span>)}</div>}
      {calibration?.limitations && <p className="chart-note">{Array.isArray(calibration.limitations) ? calibration.limitations.join('；') : calibration.limitations}</p>}
    </>}
  </section>
}

function FinalEvaluation({ evaluation, unavailable }: { evaluation: Evaluation | null; unavailable: boolean }) {
  const [scope, setScope] = useState<'all' | 'catalog'>('all')
  const [task, setTask] = useState<Task>('pitch')
  const selectedScope = scope === 'catalog' && evaluation?.catalog_serving ? evaluation.catalog_serving : evaluation
  const selected = selectedScope?.selected
  const comparison = [['lightgbm_history', selectedScope?.selected], ...Object.entries(selectedScope?.baselines || {})] as [string, Partial<Record<Task, FinalMetrics>> | undefined][]
  return <section className="panel evidence final-evaluation"><div className="card-heading"><h3>2025 凍結模型最終測試</h3><span>選定模型後的一次保留評估</span></div>
    {!evaluation?.test_evaluated ? <p className="muted-message">{unavailable ? '目前尚未取得最終測試報告；不以驗證集數字代替。' : '正在讀取凍結模型的最終測試報告。'}</p> : <>
      <p className="subtle">測試期間 {evaluation.period.start}～{evaluation.period.end}；模型 {evaluation.frozen_bundle.model_version}。測試資料未用於訓練、調參、模型選擇或重新校準。</p>
      {evaluation.catalog_serving && <><div className="metric-tabs" role="group" aria-label="最終測試樣本範圍"><button aria-pressed={scope === 'all'} onClick={() => setScope('all')}>全部合格投球</button><button aria-pressed={scope === 'catalog'} onClick={() => setScope('catalog')}>網站可選投打</button></div><p className="chart-note">全體評估保留未見球員；網站子集僅包含凍結球員名單中可選的投手與打者。兩者樣本範圍不同，需分別解讀。</p></>}
      <p className="table-hint">可左右滑動查看完整表格。</p><div className="table-wrap"><table className="metric-table final-table"><caption>{scope === 'catalog' ? '網站可選投打子集' : '全部合格投球'} · 凍結模型</caption><thead><tr><th>任務</th><th>樣本數</th><th>Log loss</th><th>Top-1</th><th>Top-2</th><th>ECE</th><th>實測覆蓋率</th><th>集合大小</th></tr></thead><tbody>{tasks.filter(task => selected?.[task]).map(task => { const m = selected![task]!; return <tr key={task}><td>{taskNames[task]}</td><td>{integer(m.n)}</td><td>{decimal(m.log_loss)}</td><td>{percent(m.top1_accuracy)}</td><td>{percent(m.top2_accuracy)}</td><td>{decimal(m.ece)}</td><td>{percent(m.coverage)}</td><td>{decimal(m.mean_set_size, 2)}</td></tr> })}</tbody></table></div>
      {selectedScope?.baselines && <><div className="metric-tabs" role="group" aria-label="最終測試比較任務">{tasks.map(value => <button key={value} aria-pressed={task === value} onClick={() => setTask(value)}>{taskNames[value]}</button>)}</div><div className="table-wrap"><table className="metric-table comparison-table"><caption>相同最終測試樣本的基準比較；log loss 越低越好。</caption><thead><tr><th>模型</th><th>樣本數</th><th>Log loss</th><th>Top-1</th><th>Top-2</th><th>ECE</th></tr></thead><tbody>{comparison.filter(([, values]) => values?.[task]).map(([name, values]) => { const m = values![task]!; return <tr key={name}><td>{candidateNames[name] || name}</td><td>{integer(m.n)}</td><td>{decimal(m.log_loss)}</td><td>{percent(m.top1_accuracy)}</td><td>{percent(m.top2_accuracy)}</td><td>{decimal(m.ece)}</td></tr> })}</tbody></table></div></>}
      {selected?.pitch && selectedScope?.baselines?.pitcher_count_shrunk?.pitch && <p className="muted-message">此範圍球種 log loss：凍結模型 {decimal(selected.pitch.log_loss)}，投手收縮頻率 {decimal(selectedScope.baselines.pitcher_count_shrunk.pitch.log_loss)}。{selected.pitch.log_loss > selectedScope.baselines.pitcher_count_shrunk.pitch.log_loss ? '凍結模型未優於此基準，保留此結果，不使用測試集重新選模。' : '凍結模型在此項指標優於基準；不代表每項任務或每次對戰皆較準確。'}</p>}
      <p className="chart-note">模型 SHA-256：<code>{evaluation.frozen_bundle.sha256}</code></p>
      {!!evaluation.limitations?.length && <details><summary>最終測試的限制</summary><ul>{evaluation.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details>}
    </>}
  </section>
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
  const [prediction, setPrediction] = useState<Prediction | null>(null)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [startup, setStartup] = useState(true)
  const [retry, setRetry] = useState(0), [tab, setTab] = useState<'analysis' | 'about'>('analysis')
  const pitchTypes = metadata?.pitch_types || []
  const reconstructed = useMemo(() => reconstructSequence(sequence, pitchTypes), [sequence, pitchTypes])
  const currentBalls = sequence.length ? reconstructed.balls : balls
  const currentStrikes = sequence.length ? reconstructed.strikes : strikes
  const historyError = sequenceIssue(sequence, pitchTypes, currentBalls, currentStrikes)
  const capabilities = prediction?.capabilities || modelSummary?.capabilities || metadata?.capabilities
  const unsupportedHistory = sequence.length > 0 && !capabilities?.sequence ? '目前服務模型尚未支援歷程推論；請清空歷程使用情境分析，或待第二週模型上線。' : null
  const inputIssue = historyError || unsupportedHistory
  useEffect(() => {
    const controller = new AbortController()
    if (mode === 'fixed') { setStartup(false); setModelInfoPending(false); return () => controller.abort() }
    setStartup(true); setError(''); setModelInfoPending(true); setModelInfoError('')
    setEvaluation(null); setEvaluationUnavailable(false)
    if (!BASE && !ENV.DEV) { setError('尚未設定正式 API 網址。請設定 VITE_API_BASE_URL 後重新部署，或使用 README 的本機啟動方式。'); setStartup(false); setModelInfoPending(false); return }
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
  }, [mode])
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
    setPrediction(null); setError(''); setBusy(false); setSequence([]); setPitcher(''); setBatter(''); setFixedCases(null); setCaseId('')
    setMode(next)
  }
  const invalidate = () => setPrediction(null)
  function resetHistory() { invalidate(); setSequence([]); setBalls(0); setStrikes(0) }
  function changePlayer(role: 'pitcher' | 'batter', id: string) { resetHistory(); role === 'pitcher' ? setPitcher(id) : setBatter(id) }
  function editPitch(index: number, updates: Partial<SequencePitch>) { invalidate(); setSequence(items => items.map((item, i) => i === index ? { ...item, ...updates } : item)) }
  const pitching = players.find(p => p.id === pitcher && p.role === 'pitcher')
  const batting = players.find(p => p.id === batter && p.role === 'batter')
  const sorted = prediction ? [...prediction.pitch_probabilities].sort((a, b) => b.probability - a.probability) : []
  const maxZone = Math.max(.001, ...(prediction?.zone_probabilities.map(z => z.probability) || []))
  const updating = busy || startup
  const summary = prediction || modelSummary || metadata
  const dataAvailable = !!prediction && !updating && !error && !inputIssue
  const history = prediction?.history_summary
  const selectedCase = fixedCases?.cases.find(item => item.id === caseId)
  return <>
    <header className="header"><div className="brand"><Logo /><div><strong>球路參謀</strong><span>PITCHADVISOR TW</span></div></div><nav aria-label="主選單"><button className={tab === 'analysis' ? 'active' : ''} onClick={() => setTab('analysis')}>配球分析</button><button className={tab === 'about' ? 'active' : ''} onClick={() => setTab('about')}>資料與方法</button></nav><div className="status"><i className={error ? 'offline' : ''} />{mode === 'fixed' ? '固定案例 · 非即時' : error ? '服務待確認' : startup ? '連接分析服務' : '即時模型分析'}</div></header>
    <main>
      <section className="mode-panel" aria-label="分析模式"><div><b>{mode === 'fixed' ? '固定示範案例' : '即時模型分析'}</b><p>{mode === 'fixed' ? '此模式讀取隨網站附帶的預先計算結果，不會呼叫推論 API。僅可切換固定案例，輸入條件為唯讀。' : '調整對戰與歷程後，由模型即時計算。雲端喚醒約需 20–60 秒；也可切換固定案例展示。'}</p></div><div className="mode-buttons"><button aria-pressed={mode === 'realtime'} onClick={() => changeMode('realtime')}>即時分析</button><button aria-pressed={mode === 'fixed'} onClick={() => changeMode('fixed')}>固定示範案例</button></div>
        {mode === 'fixed' && <div className="fixed-case-picker"><strong>固定案例，非即時推論</strong>{fixedLoading ? <p role="status">正在讀取網站內的固定案例。</p> : fixedError ? <p role="alert">{fixedError}</p> : <><label htmlFor="fixed-case">選擇示範案例</label><select id="fixed-case" value={caseId} onChange={e => { setPrediction(null); setCaseId(e.target.value) }}>{fixedCases?.cases.map(item => <option key={item.id} value={item.id}>{item.title}</option>)}</select><p>{selectedCase?.description}</p><small>凍結版本 {fixedCases?.model_version} · 訓練截止 {fixedCases?.data_cutoff}<br />模型 SHA-256：<code>{fixedCases?.bundle_sha256}</code></small></>}</div>}
      </section>
      {waitingLong && <p className="warming-message" role="status">雲端服務仍在喚醒，請稍候。超過 65 秒會停止等待；可隨時使用固定示範案例。</p>}
      <section className="hero"><div><div className="eyebrow"><span />中職逐球資料與即時模型推論</div><h1>下一球的選擇，<br />多一份<span>資料依據</span></h1><p>從投打身分、當前情境與打席歷程，觀察球種、落點與結果。<br className="desktop" />看見推薦背後的樣本、模型比較與不確定性。</p></div><div className="hero-stats"><div><strong>{integer(metadata?.games)}</strong><span>歷年比賽資料</span></div><div><strong>{integer(metadata?.pitches)}</strong><span>逐球原始事件</span></div><p>2023–2025 資料已整理<br />模型訓練截止：{metadata?.data_cutoff || '載入中'}</p></div></section>
      {tab === 'about' ? <section className="about panel"><div className="eyebrow">DATA & METHODOLOGY</div><h2>讓每份推論，都能回到驗證依據。</h2><p>資料來自主辦方官網指向的 Rebas Open Data 公開逐球資料。僅讀取單場 JSON，避免 ZIP 內的合併檔重複計數。</p><div className="about-grid"><article><b>01 · 依時間切分</b><p>訓練截止 {metadata?.data_cutoff || '讀取中'}。2024 後段供驗證與獨立校準，2025 留作最終測試；模型選擇與測試狀態見下方實際摘要。</p></article><article><b>02 · 完整打席歷程</b><p>歷程從 0 壞 0 好開始，最多 16 球，逐球記錄球種、落點、球速與結果。未知量測保留空值；沒有歷程時明示為情境分析。</p></article><article><b>03 · 歷史觀察推薦</b><p>推薦以訓練期失分價值比較候選球種與落點。分數越低對投手越有利；歷史觀察無法保證改變配球後仍有相同效果。</p></article><article><b>04 · 區域與可信度</b><p>座標採投手視角，畫面右側為正。13 分區包含好球框內九宮格及框外四方向。預測集合與校準稽核按上線版本如實揭露。</p></article></div>
        <ModelEvidence summary={summary} pending={modelInfoPending} />
        <FinalEvaluation evaluation={evaluation} unavailable={evaluationUnavailable} />
        {modelInfoError && <p className="muted-message">{modelInfoError}</p>}
        <h3 className="data-table-title">年度資料概況</h3><div className="table-wrap"><table><thead><tr><th>年度</th><th>場數</th><th>逐球事件</th><th>座標缺值</th><th>球速缺值</th></tr></thead><tbody>{metadata?.by_year.map(y => <tr key={y.year}><td>{y.year}</td><td>{y.games}</td><td>{integer(y.pitches)}</td><td>{percent(y.coordinate_missing_rate)}</td><td>{percent(y.velocity_missing_rate)}</td></tr>)}</tbody></table></div><p className="source-links"><a href="https://blog.rebas.tw/articles/4136" target="_blank" rel="noreferrer">野革盃官方公告</a><a href="https://github.com/rebas-tw/rebas.tw-open-data" target="_blank" rel="noreferrer">Rebas Open Data（ODC-By）</a></p></section> : <>
        <div className="notice"><span aria-hidden="true">ⓘ</span><p>{capabilities?.sequence ? '歷程從本打席第一球輸入，球數會自動重建。所有建議均為歷史資料模型估計，請結合實際比賽判斷。' : '目前連線版本尚未啟用歷程模型；可先調整球數、出局數與壘包進行情境分析。'}</p></div>
        {error && <div className="error" role="alert"><div><b>暫時無法完成分析</b><p>{error}</p><small>免費雲端服務閒置後喚醒可能需要數十秒，請稍候再試。</small></div><button onClick={() => setRetry(n => n + 1)}>重新連線</button></div>}
        <div className="workspace"><aside className="panel controls"><div className="section-label"><span>01</span>設定對戰情境</div><h2>從一組對戰開始</h2><fieldset className="control-fields" disabled={mode === 'fixed' || startup}><label htmlFor="pitcher">投手 <span>{pitching?.hand === 'L' ? '左投' : pitching?.hand === 'R' ? '右投' : ''}</span></label><select id="pitcher" value={pitcher} disabled={startup} onChange={e => changePlayer('pitcher', e.target.value)}><option value="" disabled>選擇投手</option>{players.filter(p => p.role === 'pitcher').map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select><div className="versus">VS</div><label htmlFor="batter">打者 <span>{batting?.hand === 'L' ? '左打' : batting?.hand === 'R' ? '右打' : ''}</span></label><select id="batter" value={batter} disabled={startup} onChange={e => changePlayer('batter', e.target.value)}><option value="" disabled>選擇打者</option>{players.filter(p => p.role === 'batter').map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select><p className="control-hint">切換投打球員會開始新打席。</p><div className="separator" /><div className="count-label">目前球數 <b>{currentBalls} 壞球・{currentStrikes} 好球</b></div>
          {sequence.length > 0 && <p className="control-hint">球數由完整歷程推算；編輯下方歷程即可變更。</p>}
          <label className="small-label">壞球 B</label><div className="segments">{[0, 1, 2, 3].map(n => <button key={n} disabled={sequence.length > 0} aria-label={`${n} 壞球`} aria-pressed={currentBalls === n} className={currentBalls === n ? 'selected' : ''} onClick={() => { invalidate(); setBalls(n) }}>{n}</button>)}</div><label className="small-label">好球 S</label><div className="segments">{[0, 1, 2].map(n => <button key={n} disabled={sequence.length > 0} aria-label={`${n} 好球`} aria-pressed={currentStrikes === n} className={currentStrikes === n ? 'selected' : ''} onClick={() => { invalidate(); setStrikes(n) }}>{n}</button>)}</div><label className="small-label">目前出局數</label><div className="segments">{[0, 1, 2].map(n => <button key={n} aria-label={`${n} 出局`} aria-pressed={outs === n} className={outs === n ? 'selected' : ''} onClick={() => { invalidate(); setOuts(n) }}>{n}<span className="out-dot" /></button>)}</div><label className="small-label">目前壘包狀態</label><div className="bases" aria-label="壘包狀態">{[1, 0, 2].map(i => <button key={i} className={`base base-${i} ${bases[i] ? 'occupied' : ''}`} aria-label={`${i + 1} 壘${bases[i] ? '有人' : '無人'}`} aria-pressed={bases[i]} onClick={() => { invalidate(); setBases(b => b.map((x, j) => j === i ? !x : x)) }}><span>{i + 1}B</span></button>)}<span className="home-plate" /></div><p className="base-caption">{bases.some(Boolean) ? bases.map((x, i) => x ? `${i + 1} 壘` : '').filter(Boolean).join('、') + '有人' : '壘上無人'}，點擊可變更</p><div className="auto-update" role="status"><span className={updating ? 'spinner' : ''}>{updating ? '' : '✓'}</span>{mode === 'fixed' ? '固定案例條件 · 唯讀' : inputIssue ? '請先修正打席歷程' : updating ? '正在重新分析' : '修改條件後自動更新'}</div></fieldset></aside>
          <div className="results" aria-busy={updating}>
            <section className="panel sequence-editor" aria-labelledby="sequence-heading"><div className="card-heading"><h3 id="sequence-heading">本打席已投球歷程</h3><span>{sequence.length} / {Math.min(metadata?.sequence_schema?.max_length || MAX_SEQUENCE_LENGTH, MAX_SEQUENCE_LENGTH)} 球</span></div><fieldset className="control-fields" disabled={mode === 'fixed'}><p className="subtle">完整輸入自 0–0 起的每一球，分析的是下一球。落點與球速可留為未知；出局數、壘包請填目前狀態。</p>
              {!capabilities?.sequence && <p className="muted-message">目前服務模型未啟用歷程推論；模型更新後即可使用編輯器。</p>}
              {sequence.length === 0 ? <div className="history-empty">尚無歷程。目前使用手動球數；新增第一球後，球數改由歷程自動計算。</div> : <ol className="history-list">{sequence.map((pitch, i) => <li key={i} className="history-pitch"><div className="history-pitch-heading"><b>第 {i + 1} 球</b><button className="text-button delete-pitch" aria-label={`刪除第 ${i + 1} 球`} onClick={() => { invalidate(); setSequence(items => items.filter((_, index) => index !== i)) }}>刪除</button></div><div className="history-fields"><label>球種<select aria-label={`第 ${i + 1} 球球種`} value={pitch.pitch_type} onChange={e => editPitch(i, { pitch_type: e.target.value })}>{pitchTypes.map(type => <option key={type} value={type}>{pitchNames[type] || type} ({type})</option>)}</select></label><label>落點<select aria-label={`第 ${i + 1} 球落點`} value={pitch.zone ?? ''} onChange={e => editPitch(i, { zone: e.target.value === '' ? null : Number(e.target.value) })}><option value="">未知</option>{zones.map((name, zone) => <option key={zone} value={zone}>Z{zone + 1} · {name}</option>)}</select></label><label>球速 km/h<input aria-label={`第 ${i + 1} 球球速`} type="number" min="40" max="180" step="0.1" inputMode="decimal" placeholder="未知" value={pitch.velocity ?? ''} onChange={e => editPitch(i, { velocity: e.target.value === '' ? null : Number(e.target.value) })} /></label><label>投球結果<select aria-label={`第 ${i + 1} 球投球結果`} value={pitch.result} onChange={e => editPitch(i, { result: e.target.value as SequencePitch['result'] })}>{PITCH_RESULTS.map(result => <option key={result} value={result}>{resultNames[result]}</option>)}</select></label></div></li>)}</ol>}
              {inputIssue && <p className="history-error" role="alert">{inputIssue}</p>}
              <div className="history-actions"><button className="primary-button" disabled={startup || !capabilities?.sequence || !pitchTypes.length || sequence.length >= MAX_SEQUENCE_LENGTH || reconstructed.terminal} onClick={() => { invalidate(); setSequence(items => [...items, { pitch_type: pitchTypes[0], zone: null, velocity: null, result: 'ball' }]) }}>＋ 新增一球</button><button className="text-button" disabled={!sequence.length} onClick={resetHistory}>清空／開始新打席</button><span>{sequence.length ? `${currentBalls} 壞 ${currentStrikes} 好${reconstructed.terminal ? ' · 打席已結束' : ' · 下一球情境'}` : '無歷程情境'}</span></div></fieldset>
            </section>
            <div className="result-heading"><div><div className="section-label"><span>02</span>資料與模型給出的下一球視角</div><h2>{pitching?.name || '投手'}<small>對決</small>{batting?.name || '打者'}</h2></div><span className="chip">{mode === 'fixed' ? '固定案例 · 非即時' : inputIssue ? '歷程待修正' : updating ? '更新中' : dataAvailable ? '分析已更新' : '等待分析'}</span></div>
            {!prediction ? <div className="panel empty">{!error && !inputIssue && <div className="spinner" />}<h3>{inputIssue ? '請修正歷程後再分析' : error ? '無法取得目前情境的結果' : startup ? '正在載入球員名單' : '等待分析結果'}</h3><p>{inputIssue || (error ? '確認上方提示後重試。' : '依目前條件執行即時模型推論。')}</p></div> : <>
              <div className="charts"><section className="panel pitch-chart"><div className="card-heading"><h3>球種機率</h3><span>預測下一球</span></div><p className="subtle">模型：{prediction.model_name || prediction.model_info?.selected_candidate || prediction.model_version}</p><div className="bar-chart">{sorted.filter(p => p.probability > .003).map((p, i) => <div className="bar-row" key={p.pitch_type}><div><b>{p.name}</b><span>{p.pitch_type}</span></div><div className="bar-track"><div className={i === 0 ? 'bar lead' : 'bar'} style={{ width: `${p.probability * 100}%` }} /></div><strong>{percent(p.probability)}</strong></div>)}</div><p className="chart-note">最常出現的球種，與最有利的推薦配球不一定相同。</p></section>
                <section className="panel zone-chart"><div className="card-heading"><h3>13 分區落點分布</h3><span>投手視角</span></div><p className="subtle">實際通過位置的機率估計</p><div className="heatmap">{prediction.zone_probabilities.map(z => <div key={z.zone} className={`zone z-${z.zone}`} title={`${z.name}：${percent(z.probability)}`} style={{ backgroundColor: `rgba(38, 101, 74, ${.08 + .8 * z.probability / maxZone})`, color: z.probability / maxZone > .55 ? '#fff' : '#304a3c' }}><b>{percent(z.probability)}</b><span>{z.zone < 9 ? z.zone + 1 : z.name.replace('框外', '')}</span></div>)}</div><div className="heat-legend"><span>較低</span><i /><span>較高</span></div><p className="chart-note">好球框內 3×3；框外依上、右、下、左四方向分區。</p></section></div>
              {prediction.result_probabilities && <section className="panel outcome-panel"><div className="card-heading"><h3>下一球結果機率</h3><span>情境下的結果預測</span></div><div className="outcome-grid">{prediction.result_probabilities.map(result => <div key={result.result}><span>{resultNames[result.result] || result.result}</span><strong>{percent(result.probability)}</strong></div>)}</div></section>}
              <section className="panel recommendations"><div className="card-heading"><h3>值得考慮的配球</h3><span>期望失分變化越低越有利</span></div><div className="recommendation-list">{prediction.recommendations.length ? prediction.recommendations.slice(0, 3).map((r, i) => <article key={`${r.pitch_type}-${r.zone}`} className={i === 0 ? 'recommendation best' : 'recommendation'}><div className="rank">{i === 0 ? '優先參考' : `候選 0${i + 1}`}</div><h4>{pitchNames[r.pitch_type] || r.pitch_type}<span>↗</span></h4><p>{zones[r.zone]} <span className="code">{r.pitch_type} / Z{r.zone + 1}</span></p><div className="value">{r.expected_run_change > 0 ? '+' : ''}{r.expected_run_change.toFixed(3)}<small>期望失分變化</small></div><small>直接情境 {integer(r.direct_sample_count)} 球<br />球種與落點彙整 {integer(r.pooled_sample_count)} 球</small><span className="support">{r.support === 'pooled' ? '使用群體樣本補充' : '歷史樣本支持'}</span></article>) : <p>目前沒有足夠資料支持的候選配球。</p>}</div><p className="chart-note">依歷史觀察與訓練期失分價值估計，無法保證改變配球後的因果效果。候選條件結果頭的可信度與下一球主結果頭分開評估。</p></section>
              <section className="panel confidence"><div className="card-heading"><h3>這次分析有多少資料支持？</h3><span>訓練期樣本</span></div><div className="sample-grid">{[['pitcher', '投手逐球'], ['batter', '打者面對投球'], ['matchup', '直接投打對戰'], ['league_state', '聯盟相同情境']].map(([key, label]) => <div key={key}><strong>{integer(prediction.sample_counts[key])}</strong><span>{label}</span></div>)}</div>
                <div className="history-receipt"><b>{prediction.sequence_used ? '已使用本打席歷程' : '本次為無歷程情境分析'}</b>{history && <span>{integer(history.length)} 球 · 落點未知 {integer(history.missing_zone_count)} 球 · 球速未知 {integer(history.missing_velocity_count)} 球</span>}<span>{capabilities?.batter_conditioned_model ? '模型包含打者條件特徵' : '此版本尚未提供打者條件模型'}</span></div>
                <h4 className="prediction-set-heading">下一球預測集合</h4><p className="subtle">集合列出目前機率仍需保留的可能答案。集合越大，代表模型越難縮小範圍；並非單次預測有 90% 正確率。</p>
                {capabilities?.conformal && prediction.prediction_sets ? <div className="prediction-sets">{tasks.map(task => {
                  const set = prediction.prediction_sets?.[task]
                  return <div className="prediction-set" key={task}><b>{taskNames[task]} <small>名目 {percent(set?.target_coverage)}</small></b>{set && set.threshold != null ? <div className="set-labels">{set.labels.length ? set.labels.map(label => <span key={String(label)}>{labelFor(task, label)}</span>) : <em>本次集合為空；模型無法提供符合門檻的候選。</em>}</div> : <p>此任務尚無有效集合門檻。</p>}</div>
                })}</div> : <p className="muted-message">此版本尚未提供已校準的預測集合。</p>}
                <details><summary>資料限制與目前能力</summary><ul>{prediction.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details></section>
              <div className="result-meta">{prediction.model_version} · 訓練截止 {prediction.data_cutoff}<span>{mode === 'fixed' ? '固定案例預先計算結果' : prediction.source_mode === 'supabase_verified_snapshot' ? 'Supabase 版本已核對' : prediction.source_mode === 'local_snapshot' ? '本機模型快照' : '雲端未核對，使用本機快照'} · {prediction.elapsed_ms} ms</span></div>
            </>}
            <ModelEvidence summary={summary} pending={modelInfoPending} />
        <FinalEvaluation evaluation={evaluation} unavailable={evaluationUnavailable} />
            {modelInfoError && <p className="muted-message">{modelInfoError}</p>}
          </div></div>
      </>}
      <footer><div className="brand footer-brand"><Logo /><strong>球路參謀</strong></div><p>資料來源：<a href="https://github.com/rebas-tw/rebas.tw-open-data" target="_blank" rel="noreferrer">Rebas Open Data</a> · ODC-By<br />使用資料與模型輔助判斷；估計值依訓練資料與模型能力而定。</p><span>PITCHADVISOR TW / 2026</span></footer>
    </main>
  </>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
