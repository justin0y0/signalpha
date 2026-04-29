import { useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Play, RotateCcw, TrendingUp, TrendingDown, Minus, ChevronDown } from 'lucide-react'
import { ComposedChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts'
import { api } from '../api/client'
import type { BacktestResponse } from '../types'

const SECTORS = ['','Technology','Financial Services','Healthcare','Consumer Cyclical','Consumer Defensive','Industrials','Energy','Communication Services']
const C = { cyan:'#38bdf8', purple:'#a78bfa', green:'#4ade80', red:'#f87171', amber:'#fbbf24', muted:'#475569' }
const pct = (v:number,d=2) => `${v>=0?'+':''}${(v*100).toFixed(d)}%`
const fmt2 = (v:number) => v.toFixed(2)
type Kpi = { label:string; value:string; sub?:string; color:string }

function KpiCard({k,delay}:{k:Kpi;delay:number}) {
  return (
    <motion.div className="bt-kpi" initial={{opacity:0,y:10}} animate={{opacity:1,y:0}} transition={{delay}} style={{borderTop:`2px solid ${k.color}`}}>
      <div className="bt-kpi__label">{k.label}</div>
      <div className="bt-kpi__value" style={{color:k.color}}>{k.value}</div>
      {k.sub && <div className="bt-kpi__sub">{k.sub}</div>}
    </motion.div>
  )
}

function ConfMatrix({cm}:{cm:number[][]}) {
  const labels = ['DOWN','FLAT','UP']
  const max = Math.max(...cm.flat())
  return (
    <div className="bt-cm">
      <div className="bt-cm__corner"><span>P↓ A→</span></div>
      {labels.map(l=><div key={l} className="bt-cm__head">{l}</div>)}
      {cm.map((row,pi)=>(
        <>
          <div key={`r${pi}`} className="bt-cm__rlabel">{labels[pi]}</div>
          {row.map((v,ai)=>{
            const hit=pi===ai
            const intensity=max>0?v/max:0
            const bg=hit?`rgba(56,189,248,${0.08+intensity*0.5})`:`rgba(248,113,113,${intensity*0.3})`
            return (
              <motion.div key={`${pi}${ai}`} className="bt-cm__cell" style={{background:bg}}
                initial={{scale:0.8,opacity:0}} animate={{scale:1,opacity:1}} transition={{delay:0.05*(pi*3+ai)}}>
                <span className="bt-cm__n">{v.toLocaleString()}</span>
              </motion.div>
            )
          })}
        </>
      ))}
    </div>
  )
}

function DirCard({d}:{d:{direction:string;signals:number;hits:number;hit_rate:number;avg_return_pct:number}}) {
  const isUp=d.direction==='UP'; const color=isUp?C.green:C.red; const Icon=isUp?TrendingUp:TrendingDown
  return (
    <motion.div className="bt-dir" initial={{opacity:0,x:isUp?-8:8}} animate={{opacity:1,x:0}} transition={{delay:0.2}} style={{borderLeft:`3px solid ${color}`}}>
      <div className="bt-dir__head" style={{color}}><Icon size={13}/><span>{d.direction} signals</span></div>
      <div className="bt-dir__row"><span>Signals taken</span><b>{d.signals.toLocaleString()}</b></div>
      <div className="bt-dir__row"><span>Hit rate</span><b style={{color}}>{(d.hit_rate*100).toFixed(1)}%</b></div>
      <div className="bt-dir__row"><span>Avg return</span><b style={{color:d.avg_return_pct>=0?C.green:C.red}}>{d.avg_return_pct>=0?'+':''}{d.avg_return_pct.toFixed(2)}%</b></div>
    </motion.div>
  )
}

const CustomTooltip=({active,payload,label}:any)=>{
  if(!active||!payload?.length) return null
  const eq=payload.find((p:any)=>p.dataKey==='equity')
  const dd=payload.find((p:any)=>p.dataKey==='drawdown')
  return (
    <div className="bt-tooltip">
      <div className="bt-tooltip__date">{label}</div>
      {eq&&<div>Equity <b style={{color:C.cyan}}>{eq.value>=0?'+':''}{eq.value.toFixed(2)}%</b></div>}
      {dd&&<div>Drawdown <b style={{color:C.red}}>{dd.value.toFixed(2)}%</b></div>}
    </div>
  )
}

export function BacktestingPage() {
  const [ticker,setTicker]=useState('')
  const [sector,setSector]=useState('')
  const [startDate,setStartDate]=useState('2022-01-01')
  const [endDate,setEndDate]=useState('2026-04-01')
  const [threshold,setThreshold]=useState(0.65)
  const [running,setRunning]=useState(false)
  const [result,setResult]=useState<BacktestResponse|null>(null)
  const [error,setError]=useState<string|null>(null)
  const resultRef=useRef<HTMLDivElement>(null)

  const run=async()=>{
    setRunning(true); setError(null)
    try {
      const r=await api.runBacktest({ticker:ticker||undefined,sector:sector||undefined,start_date:startDate,end_date:endDate,probability_threshold:threshold})
      setResult(r)
      setTimeout(()=>resultRef.current?.scrollIntoView({behavior:'smooth',block:'start'}),100)
    } catch(e:any) { setError(e?.message??'Backtest failed') }
    finally { setRunning(false) }
  }

  const chartData=result?.equity_curve.map(p=>({
    date:new Date(p.date).toLocaleDateString('en-US',{month:'short',year:'2-digit'}),
    equity:+((p.equity-1)*100).toFixed(3),
    drawdown:+(p.drawdown*100).toFixed(3),
  }))??[]

  const ret=result?.total_return??0
  const kpis:Kpi[]=result?[
    {label:'Total Return',value:pct(ret),sub:`${result.total_trades} trades`,color:ret>=0?C.green:C.red},
    {label:'Sharpe Ratio',value:fmt2(result.sharpe_ratio),sub:'annualised',color:result.sharpe_ratio>1?C.green:result.sharpe_ratio>0?C.cyan:C.red},
    {label:'Sortino',value:fmt2(result.sortino_ratio),sub:'downside-adjusted',color:result.sortino_ratio>1?C.green:C.cyan},
    {label:'Max Drawdown',value:pct(result.max_drawdown),sub:'peak to trough',color:C.red},
    {label:'Win Rate',value:`${(result.win_rate*100).toFixed(1)}%`,sub:`of ${result.total_trades} trades`,color:result.win_rate>0.5?C.green:C.amber},
    {label:'Profit Factor',value:result.profit_factor>=99?'∞':fmt2(result.profit_factor),sub:'gross win / gross loss',color:result.profit_factor>1.5?C.green:result.profit_factor>1?C.cyan:C.red},
    {label:'Avg Win / Loss',value:`+${result.avg_win_pct.toFixed(2)}%`,sub:`loss ${result.avg_loss_pct.toFixed(2)}%`,color:C.green},
  ]:[]

  return (
    <div className="bt-page">
      <motion.div className="bt-hero" initial={{opacity:0,y:-8}} animate={{opacity:1,y:0}}>
        <div className="bt-hero__badge"><span className="bt-hero__dot"/>BACKTESTER</div>
        <h1 className="bt-hero__title">Strategy Simulator</h1>
        <p className="bt-hero__sub">Replay the ML signal on 5,393 historical earnings events. Adjust confidence threshold and scope to explore risk/return tradeoffs.</p>
      </motion.div>

      <motion.div className="bt-config" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} transition={{delay:0.08}}>
        <div className="bt-config__grid">
          <div className="bt-field">
            <label>Ticker</label>
            <input value={ticker} onChange={e=>setTicker(e.target.value.toUpperCase())} placeholder="All tickers" className="bt-input"/>
          </div>
          <div className="bt-field">
            <label>Sector</label>
            <div className="bt-select-wrap">
              <select value={sector} onChange={e=>setSector(e.target.value)} className="bt-select">
                {SECTORS.map(s=><option key={s} value={s}>{s||'All sectors'}</option>)}
              </select>
              <ChevronDown size={13} className="bt-select-icon"/>
            </div>
          </div>
          <div className="bt-field">
            <label>Start date</label>
            <input type="date" value={startDate} onChange={e=>setStartDate(e.target.value)} className="bt-input"/>
          </div>
          <div className="bt-field">
            <label>End date</label>
            <input type="date" value={endDate} onChange={e=>setEndDate(e.target.value)} className="bt-input"/>
          </div>
          <div className="bt-field">
            <label>Min confidence <span className="bt-conf-val">{(threshold*100).toFixed(0)}%</span></label>
            <input type="range" min="0.5" max="0.95" step="0.05" value={threshold} onChange={e=>setThreshold(+e.target.value)} className="bt-slider"/>
            <div className="bt-slider-labels"><span>50%</span><span>95%</span></div>
          </div>
          <div className="bt-field bt-field--actions">
            <button className="bt-run" onClick={run} disabled={running}>
              {running?<><span className="bt-run__spinner"/>Running…</>:<><Play size={14}/>Run backtest</>}
            </button>
            {result&&<button className="bt-reset" onClick={()=>{setResult(null);setError(null)}}><RotateCcw size={13}/></button>}
          </div>
        </div>
      </motion.div>

      {error&&<motion.div className="bt-error" initial={{opacity:0}} animate={{opacity:1}}>{error}</motion.div>}

      <AnimatePresence>
        {result&&result.total_samples>0&&(
          <motion.div ref={resultRef} initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}}>
            <div className="bt-kpi-strip">
              {kpis.map((k,i)=><KpiCard key={k.label} k={k} delay={i*0.05}/>)}
            </div>

            <motion.div className="bt-card" initial={{opacity:0,y:12}} animate={{opacity:1,y:0}} transition={{delay:0.15}}>
              <div className="bt-card__title">
                <TrendingUp size={13}/>Equity Curve & Drawdown
                <span className="bt-card__pill" style={{color:ret>=0?C.green:C.red,background:ret>=0?'rgba(74,222,128,0.1)':'rgba(248,113,113,0.1)'}}>{pct(ret)}</span>
              </div>
              <div style={{height:220}}>
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{top:4,right:16,bottom:0,left:4}}>
                    <defs>
                      <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={ret>=0?C.green:C.red} stopOpacity={0.25}/>
                        <stop offset="100%" stopColor={ret>=0?C.green:C.red} stopOpacity={0.02}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)"/>
                    <XAxis dataKey="date" tick={{fill:'#64748b',fontSize:10}} axisLine={false} tickLine={false} minTickGap={60}/>
                    <YAxis tick={{fill:'#64748b',fontSize:10}} axisLine={false} tickLine={false} tickFormatter={v=>`${v>=0?'+':''}${v.toFixed(0)}%`}/>
                    <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" strokeDasharray="4 3"/>
                    <Tooltip content={<CustomTooltip/>}/>
                    <Area type="monotone" dataKey="equity" stroke={ret>=0?C.green:C.red} strokeWidth={2} fill="url(#eqGrad)" dot={false} activeDot={{r:3}}/>
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
              <div className="bt-chart-divider">DRAWDOWN</div>
              <div style={{height:110}}>
                <ResponsiveContainer width="100%" height="100%">
                  <ComposedChart data={chartData} margin={{top:0,right:16,bottom:4,left:4}}>
                    <defs>
                      <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={C.red} stopOpacity={0.35}/>
                        <stop offset="100%" stopColor={C.red} stopOpacity={0.02}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)"/>
                    <XAxis dataKey="date" tick={{fill:'#64748b',fontSize:10}} axisLine={false} tickLine={false} minTickGap={60}/>
                    <YAxis tick={{fill:'#64748b',fontSize:10}} axisLine={false} tickLine={false} tickFormatter={v=>`${v.toFixed(0)}%`}/>
                    <Tooltip content={<CustomTooltip/>}/>
                    <Area type="monotone" dataKey="drawdown" stroke={C.red} strokeWidth={1.5} fill="url(#ddGrad)" dot={false}/>
                  </ComposedChart>
                </ResponsiveContainer>
              </div>
            </motion.div>

            <div className="bt-grid-2">
              <motion.div className="bt-card" initial={{opacity:0,x:-12}} animate={{opacity:1,x:0}} transition={{delay:0.2}}>
                <div className="bt-card__title">Confusion Matrix <span className="bt-card__sub">signal vs actual direction</span></div>
                <ConfMatrix cm={result.confusion_matrix}/>
                <div className="bt-cm-note">Rows = predicted signal · Cols = actual outcome · Diagonal = correct</div>
              </motion.div>
              <motion.div className="bt-card" initial={{opacity:0,x:12}} animate={{opacity:1,x:0}} transition={{delay:0.2}}>
                <div className="bt-card__title">Direction Breakdown</div>
                <div style={{display:'flex',flexDirection:'column',gap:'0.75rem',marginTop:'0.5rem'}}>
                  {result.direction_stats.map(d=><DirCard key={d.direction} d={d}/>)}
                  <div className="bt-dir" style={{borderLeft:`3px solid ${C.muted}`}}>
                    <div className="bt-dir__head" style={{color:C.muted}}><Minus size={13}/><span>FLAT / skipped</span></div>
                    <div className="bt-dir__row"><span>Events skipped</span><b>{(result.total_samples-result.total_trades).toLocaleString()}</b></div>
                    <div className="bt-dir__row"><span>Skip rate</span><b>{((result.total_samples-result.total_trades)/result.total_samples*100).toFixed(1)}%</b></div>
                  </div>
                </div>
                <div className="bt-ml-grid">
                  {[['Accuracy',(result.accuracy*100).toFixed(1)+'%'],['Precision',(result.precision_weighted*100).toFixed(1)+'%'],['Recall',(result.recall_weighted*100).toFixed(1)+'%'],['F1',(result.f1_weighted*100).toFixed(1)+'%']].map(([l,v])=>(
                    <div key={l} className="bt-ml-cell"><span>{l}</span><b>{v}</b></div>
                  ))}
                </div>
              </motion.div>
            </div>
          </motion.div>
        )}
        {result&&result.total_samples===0&&(
          <motion.div className="bt-empty" initial={{opacity:0}} animate={{opacity:1}}>No events matched your filters.</motion.div>
        )}
      </AnimatePresence>

      {!result&&!error&&(
        <motion.div className="bt-empty" initial={{opacity:0}} animate={{opacity:1}}>
          <Play size={28} style={{opacity:0.25,marginBottom:10}}/>
          <p>Configure parameters above and run the backtest.</p>
          <p style={{fontSize:'0.78rem',marginTop:4,color:'#475569'}}>Strategy: LONG on UP · SHORT on DOWN · SKIP on FLAT</p>
        </motion.div>
      )}
    </div>
  )
}
