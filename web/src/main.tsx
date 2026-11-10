import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

type Player={id:string;name:string;role:'pitcher'|'batter';hand:string|null;sample_count:number}
type Recommendation={pitch_type:string;zone:number;expected_run_change:number;direct_sample_count:number;pooled_sample_count:number;support:string}
type Prediction={pitch_probabilities:{pitch_type:string;name:string;probability:number}[];zone_probabilities:{zone:number;name:string;probability:number}[];recommendations:Recommendation[];sample_counts:Record<string,number>;warnings:string[];model_version:string;data_version:string;data_cutoff:string;source_mode:string;elapsed_ms:number}
type Metadata={games:number|null;pitches:number|null;training_pitches:number;data_cutoff:string;by_year:{year:number;games:number;pitches:number;coordinate_missing_rate:number;velocity_missing_rate:number}[]}
const ENV=(import.meta as ImportMeta & {env:Record<string,string>}).env
const BASE=ENV.VITE_API_BASE_URL?.replace(/\/$/,'') || (ENV.DEV ? '/api' : '')
const pitchNames:Record<string,string>={FF:'四縫線',SI:'伸卡／二縫線',FC:'卡特',SL:'滑球',CU:'曲球',CH:'變速球',FO:'指叉',FS:'快速指叉',KN:'蝴蝶球',EP:'小便球'}
const zones=['左上','中上','右上','左中','正中','右中','左下','中下','右下','帶外上方','帶外右側','帶外下方','帶外左側']
const percent=(n:number)=>`${(n*100).toFixed(1)}%`
const integer=(n:number|undefined|null)=>n==null?'—':new Intl.NumberFormat('zh-TW').format(n)
async function read<T>(url:string,options?:RequestInit):Promise<T>{
  const response=await fetch(BASE+url,options)
  if(!response.ok){
    const body=await response.json().catch(()=>({}))
    throw new Error(typeof body.detail==='string'?body.detail:`服務回應 ${response.status}，請稍後重試。`)
  }
  return response.json()
}
function Logo(){return <svg viewBox="0 0 44 44" width="38" aria-hidden="true"><circle cx="22" cy="22" r="20" fill="#c9df94"/><path d="M8 8c13 6 13 22 0 28M36 8c-13 6-13 22 0 28" stroke="#1c3d32" strokeWidth="1.7" fill="none"/><path d="m12 13 5-3m-2 10 5-1m-6 8 5 1m-7 5 5 3m15-23-5-3m2 10-5-1m6 8-5 1m7 5-5 3" stroke="#1c3d32" strokeWidth="1.2"/></svg>}

function App(){
  const[players,setPlayers]=useState<Player[]>([])
  const[metadata,setMetadata]=useState<Metadata|null>(null)
  const[pitcher,setPitcher]=useState(''),[batter,setBatter]=useState('')
  const[balls,setBalls]=useState(1),[strikes,setStrikes]=useState(2),[outs,setOuts]=useState(0)
  const[bases,setBases]=useState([false,false,false])
  const[prediction,setPrediction]=useState<Prediction|null>(null)
  const[busy,setBusy]=useState(false),[error,setError]=useState(''),[startup,setStartup]=useState(true)
  const[retry,setRetry]=useState(0),[tab,setTab]=useState<'analysis'|'about'>('analysis')
  useEffect(()=>{
    const controller=new AbortController();setStartup(true);setError('')
    if(!BASE && !ENV.DEV){setError('尚未設定雲端 API 網址。請設定 VITE_API_BASE_URL 後重新建置，或使用 README 的本機啟動方式。');setStartup(false);return}
    Promise.all([read<{players:Player[]}>('/players',{signal:controller.signal}),read<Metadata>('/metadata',{signal:controller.signal})])
      .then(([catalog,meta])=>{setPlayers(catalog.players);setMetadata(meta);setPitcher(p=>p||catalog.players.find(x=>x.role==='pitcher')?.id||'');setBatter(p=>p||catalog.players.find(x=>x.role==='batter')?.id||'')})
      .catch(e=>{if(!controller.signal.aborted)setError(e.message)})
      .finally(()=>{if(!controller.signal.aborted)setStartup(false)})
    return()=>controller.abort()
  },[retry])
  useEffect(()=>{
    if(!pitcher||!batter)return
    const controller=new AbortController();setBusy(true);setError('');setPrediction(null)
    const timer=setTimeout(()=>{
      read<Prediction>('/predict',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,
        body:JSON.stringify({pitcher_id:pitcher,batter_id:batter,state:{balls,strikes,outs,bases},sequence:[]})})
        .then(result=>{if(!controller.signal.aborted)setPrediction(result)})
        .catch(e=>{if(!controller.signal.aborted)setError(e.message)})
        .finally(()=>{if(!controller.signal.aborted)setBusy(false)})
    },250)
    return()=>{clearTimeout(timer);controller.abort()}
  },[pitcher,batter,balls,strikes,outs,bases,retry])
  const pitching=players.find(p=>p.id===pitcher&&p.role==='pitcher')
  const batting=players.find(p=>p.id===batter&&p.role==='batter')
  const sorted=prediction?[...prediction.pitch_probabilities].sort((a,b)=>b.probability-a.probability):[]
  const maxZone=Math.max(.001,...(prediction?.zone_probabilities.map(z=>z.probability)||[]))
  const updating=busy||startup
  const dataAvailable=!!prediction&&!updating&&!error
  return <>
    <header className="header"><div className="brand"><Logo/><div><strong>球路參謀</strong><span>PITCHADVISOR TW</span></div></div><nav aria-label="主選單"><button className={tab==='analysis'?'active':''} onClick={()=>setTab('analysis')}>配球分析</button><button className={tab==='about'?'active':''} onClick={()=>setTab('about')}>資料與方法</button></nav><div className="status"><i className={error?'offline':''}/>{error?'服務待確認':startup?'連接分析服務':'歷史資料基準'}</div></header>
    <main>
      <section className="hero"><div><div className="eyebrow"><span/>中職歷史資料・第一週基準</div><h1>面對這名打者，<br/>我該<span>怎麼投？</span></h1><p>從投手的配球傾向出發，查看落點與候選球路。<br className="desktop"/>讓資料支持你的判斷，也看見每個建議的限制。</p></div><div className="hero-stats"><div><strong>{integer(metadata?.games)}</strong><span>場例行賽資料</span></div><div><strong>{integer(metadata?.pitches)}</strong><span>筆原始投球事件</span></div><p>2023–2025 資料已查核<br/>模型訓練截止：{metadata?.data_cutoff||'載入中'}</p></div></section>
      {tab==='about'?<section className="about panel"><div className="eyebrow">DATA & METHODOLOGY</div><h2>先理解資料，再理解建議。</h2><p>資料由主辦方官網連到 Rebas Open Data 的公開版本下載。只讀取單場比賽 JSON，排除 ZIP 內的合併檔，避免重複計算。</p><div className="about-grid"><article><b>01　時間切分</b><p>訓練截止 {metadata?.data_cutoff}。2024 年後段分為驗證與校準集，2025 年保留作測試，本週未以測試集挑模型。</p></article><article><b>02　目前能力</b><p>本版依投手與球數估計球種，落點以投手／球種統計平滑。打者目前只用於對戰樣本查核；序列模型及預測集合於第二週開發。</p></article><article><b>03　推薦解讀</b><p>候選依歷史資料的估計失分變化排序，數值較低較有利於投手。小樣本會向較大的統計群體平滑，不能解釋為改投某球必定降低失分。</p></article><article><b>04　人工落點</b><p>座標是人工紀錄的實際進壘位置，採投手視角，並非意圖落點。13 區包括帶內九宮格，以及按正規化偏離分配的帶外四區。</p></article></div><h3>年度資料品質</h3><div className="table-wrap"><table><thead><tr><th>年度</th><th>場數</th><th>投球事件</th><th>座標缺值</th><th>球速缺值</th></tr></thead><tbody>{metadata?.by_year.map(y=><tr key={y.year}><td>{y.year}</td><td>{y.games}</td><td>{integer(y.pitches)}</td><td>{percent(y.coordinate_missing_rate)}</td><td>{percent(y.velocity_missing_rate)}</td></tr>)}</tbody></table></div><p className="source-links"><a href="https://blog.rebas.tw/articles/4136" target="_blank" rel="noreferrer">野革盃官網 ↗</a><a href="https://github.com/rebas-tw/rebas.tw-open-data" target="_blank" rel="noreferrer">Rebas Open Data／ODC-By ↗</a></p></section>:<>
      <div className="notice"><span>ⓘ</span><p>第一週版本依投手與球數估計配球；打者用於樣本查核。已投球序列與校準功能排定於第二週。</p></div>
      {error&&<div className="error" role="alert"><div><b>目前無法完成分析</b><p>{error}</p><small>免費雲端服務首次啟動可能需要較久，請稍後重試。</small></div><button onClick={()=>setRetry(n=>n+1)}>重新連線 ↻</button></div>}
      <div className="workspace"><aside className="panel controls"><div className="section-label"><span>01</span>設定對戰情境</div><h2>從一組對戰開始</h2><label htmlFor="pitcher">投手 <span>{pitching?.hand==='L'?'左投':pitching?.hand==='R'?'右投':''}</span></label><select id="pitcher" value={pitcher} disabled={startup} onChange={e=>setPitcher(e.target.value)}><option value="" disabled>選擇投手</option>{players.filter(p=>p.role==='pitcher').map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><div className="versus">VS</div><label htmlFor="batter">打者 <span>{batting?.hand==='L'?'左打':batting?.hand==='R'?'右打':''}</span></label><select id="batter" value={batter} disabled={startup} onChange={e=>setBatter(e.target.value)}><option value="" disabled>選擇打者</option>{players.filter(p=>p.role==='batter').map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><div className="separator"/><div className="count-label">目前球數 <b>{balls} 壞球－{strikes} 好球</b></div><label className="small-label">壞球 B</label><div className="segments">{[0,1,2,3].map(n=><button key={n} aria-label={`${n} 壞球`} aria-pressed={balls===n} className={balls===n?'selected':''} onClick={()=>setBalls(n)}>{n}</button>)}</div><label className="small-label">好球 S</label><div className="segments">{[0,1,2].map(n=><button key={n} aria-label={`${n} 好球`} aria-pressed={strikes===n} className={strikes===n?'selected':''} onClick={()=>setStrikes(n)}>{n}</button>)}</div><label className="small-label">出局數</label><div className="segments">{[0,1,2].map(n=><button key={n} aria-label={`${n} 出局`} aria-pressed={outs===n} className={outs===n?'selected':''} onClick={()=>setOuts(n)}>{n}<span className="out-dot"/></button>)}</div><label className="small-label">壘包狀態</label><div className="bases" aria-label="壘包狀態">{[1,0,2].map(i=><button key={i} className={`base base-${i} ${bases[i]?'occupied':''}`} aria-label={`${i+1} 壘${bases[i]?'有人':'無人'}`} aria-pressed={bases[i]} onClick={()=>setBases(b=>b.map((x,j)=>j===i?!x:x))}><span>{i+1}B</span></button>)}<span className="home-plate"/></div><p className="base-caption">{bases.some(Boolean)?bases.map((x,i)=>x?`${i+1} 壘`:'').filter(Boolean).join('、')+'有人':'壘上無人'}・點擊切換</p><div className="auto-update"><span className={updating?'spinner':''}>{updating?'':'↻'}</span>{updating?'正在重新分析…':'修改條件後自動分析'}</div></aside>
      <div className={`results ${updating?'updating':''}`} aria-busy={updating}>
        <div className="result-heading"><div><div className="section-label"><span>02</span>歷史資料下的下一球</div><h2>{pitching?.name||'投手'}<small>對上</small>{batting?.name||'打者'}</h2></div><span className="chip">{updating?'更新中':dataAvailable?'分析已更新':'等待分析'}</span></div>
        {!prediction?<div className="panel empty">{!error&&<div className="spinner"/>}<h3>{error?'未取得目前情境的結果':startup?'正在載入球員名單':'等待分析結果'}</h3><p>{error?'請確認服務狀態後重試。':'準備真實資料的配球基準。'}</p></div>:<>
        <div className="charts"><section className="panel pitch-chart"><div className="card-heading"><h3>球種機率</h3><span>配球傾向</span></div><p className="subtle">依投手與目前球數平滑估計</p><div className="bar-chart">{sorted.filter(p=>p.probability>.003).map((p,i)=><div className="bar-row" key={p.pitch_type}><div><b>{p.name}</b><span>{p.pitch_type}</span></div><div className="bar-track"><div className={i===0?'bar lead':'bar'} style={{width:`${p.probability*100}%`}}/></div><strong>{percent(p.probability)}</strong></div>)}</div><p className="chart-note">最常出現的球種，與估計最有利的球路不一定相同。</p></section>
        <section className="panel zone-chart"><div className="card-heading"><h3>13 區落點分布</h3><span>投手視角</span></div><p className="subtle">實際進壘位置的機率估計</p><div className="heatmap">{prediction.zone_probabilities.map(z=><div key={z.zone} className={`zone z-${z.zone}`} title={`${z.name}：${percent(z.probability)}`} style={{backgroundColor:`rgba(38, 101, 74, ${.08+.8*z.probability/maxZone})`,color:z.probability/maxZone>.55?'#fff':'#304a3c'}}><b>{percent(z.probability)}</b><span>{z.zone<9?z.zone+1:z.name.replace('帶外','')}</span></div>)}</div><div className="heat-legend"><span>較低</span><i/><span>較高</span></div><p className="chart-note">好球帶內 3×3，外加上、右、下、左四個互斥區域。</p></section></div>
        <section className="panel recommendations"><div className="card-heading"><h3>可以考慮的球路</h3><span>估計失分變化由低至高</span></div><div className="recommendation-list">{prediction.recommendations.length?prediction.recommendations.slice(0,3).map((r,i)=><article key={`${r.pitch_type}-${r.zone}`} className={i===0?'recommendation best':'recommendation'}><div className="rank">{i===0?'優先參考':`候選 0${i+1}`}</div><h4>{pitchNames[r.pitch_type]||r.pitch_type}<span>↗</span></h4><p>{zones[r.zone]} <span className="code">{r.pitch_type} / Z{r.zone+1}</span></p><div className="value">{r.expected_run_change>0?'+':''}{r.expected_run_change.toFixed(3)}<small>估計失分變化</small></div><small>直接情境 {integer(r.direct_sample_count)} 筆<br/>球種／區域群體 {integer(r.pooled_sample_count)} 筆</small><span className="support">{r.support==='pooled'?'使用群體平滑':'歷史樣本支持'}</span></article>):<p>目前沒有足夠資料支持可推薦的候選。</p>}</div><p className="chart-note">數值越低越有利於投手；來自歷史觀測與平滑估計，不代表實際改投後的因果效果。</p></section>
        <section className="panel confidence"><div className="card-heading"><h3>這個分析有多少資料支持？</h3><span>訓練期樣本</span></div><div className="sample-grid">{[['pitcher','投手投球'],['batter','打者面對投球'],['matchup','直接投打對戰'],['league_state','聯盟相同情境']].map(([k,label])=><div key={k}><strong>{integer(prediction.sample_counts[k])}</strong><span>{label}</span></div>)}</div><details><summary>查看資料限制與目前模型能力</summary><ul>{prediction.warnings.map((w,i)=><li key={i}>{w}</li>)}</ul></details></section>
        <div className="result-meta">{prediction.model_version} · 截止 {prediction.data_cutoff}<span>{prediction.source_mode.includes('supabase')?'Supabase 版本查核／快照':'本機資料快照'} · {prediction.elapsed_ms} ms</span></div>
        </>}
      </div></div></>}
      <footer><div className="brand footer-brand"><Logo/><strong>球路參謀</strong></div><p>資料來源：<a href="https://github.com/rebas-tw/rebas.tw-open-data" target="_blank" rel="noreferrer">Rebas Open Data</a> · ODC-By<br/>部分資料為人工紀錄，非球場儀器量測。模型估計供分析參考。</p><span>PITCHADVISOR TW / 2026</span></footer>
    </main>
  </>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>)
