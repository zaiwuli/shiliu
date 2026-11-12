import { Fragment, useEffect, useState } from 'react'
import './ledger.css'

type Stats=Record<string,number>
type Part={name:string;page:number|null;reason:string;added:number;failed:number|null;recovered:number;remaining:number;sync:Stats}
type Entry={id:number;name:string;kind:string;trigger:string;status:string;create_time:string;finished_at:string|null;added:number;failed:number|null;recovered:number;remaining:number;parts:Part[];sync:Stats;historical:boolean;message:string|null}
type Event={id:number;create_time:string;status:string;message:string|null;details?:{processed?:number;total?:number;stats?:Stats}}
type Detail=Entry&{logs:{time:string;message:string}[];retries:Event[];history:Event[]}
const names:Record<string,string>={completed:'已完成',running:'运行中',stopped:'已停止',interrupted:'已中断',failed:'失败',scheduled:'定时',manual:'手动',import:'导入',unknown:'未记录',inserted:'新增',existing:'已存在',pending:'待同步',conflict:'冲突',skipped:'跳过'}
const format=(value:string|null)=>value?new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'—'
async function read<T>(path:string,signal?:AbortSignal):Promise<T>{const r=await fetch('/api'+path,{signal});if(!r.ok)throw Error(`读取台账失败（${r.status}）`);return r.json()}
function syncStatus(e:Entry){return e.sync.pending?'待同步':e.sync.failed||e.sync.conflict?'待处理':Object.values(e.sync).some(Boolean)?'已同步':'暂无数据'}
function syncMessage(message:string|null){
 try{const v=JSON.parse(message||'{}');return [v.operation,Object.entries(v.stats||{}).map(([k,n])=>`${names[k]||k} ${n}`).join(' · '),v.error].filter(Boolean).join(' · ')}catch{return message||'—'}
}

export function Ledger({mode}:{mode:'crawl'|'sync'}){
 const [page,setPage]=useState(1),[size,setSize]=useState(10),[filter,setFilter]=useState('')
 const [data,setData]=useState<{items:Entry[];total:number;page:number;pages:number}>({items:[],total:0,page:1,pages:1})
 const [expanded,setExpanded]=useState<number|null>(null),[detail,setDetail]=useState<Detail|null>(null),[tab,setTab]=useState('板块明细')
 const [error,setError]=useState(''),[detailError,setDetailError]=useState(''),[loading,setLoading]=useState(true),[refresh,setRefresh]=useState(0)
 const [executionHistory,setExecutionHistory]=useState<Event[]|null>(null)
 useEffect(()=>{setExpanded(null);setTab('板块明细');setExecutionHistory(null)},[mode,page,size,filter])
 useEffect(()=>{
  const controller=new AbortController();let running=false
  setLoading(true);setError('')
  const load=async()=>{if(running)return;running=true;try{const result=await read<typeof data>(`/ledger?page=${page}&page_size=${size}&trigger=${filter}`,controller.signal);setData(result);setError('')}catch(e){if(!controller.signal.aborted)setError((e as Error).message)}finally{running=false;if(!controller.signal.aborted)setLoading(false)}}
  void load();const timer=setInterval(load,5000);return()=>{controller.abort();clearInterval(timer)}
 },[page,size,filter,refresh])
 useEffect(()=>{
  if(expanded===null){setDetail(null);return}
  const controller=new AbortController();setDetail(null);setDetailError('');let running=false
  const load=async()=>{if(running)return;running=true;try{setDetail(await read<Detail>(`/ledger/${expanded}`,controller.signal));setDetailError('')}catch(e){if(!controller.signal.aborted)setDetailError((e as Error).message)}finally{running=false}}
  void load();const timer=setInterval(load,5000);return()=>{controller.abort();clearInterval(timer)}
 },[expanded,refresh])
 const changePage=(next:number)=>{setPage(next);setExpanded(null)}
 const sync=mode==='sync'
 const open=(id:number)=>{setExpanded(expanded===id?null:id);setTab('板块明细')}
 return <section className="ledger-content">
  <div className="ledger-intro"><h2>{sync?'同步台账':'采集台账'}</h2><div className="ledger-filter">{[['','全部'],['scheduled','定时'],['manual','手动'],['import','CSV 导入']].map(([v,n])=><button key={v} className={filter===v?'selected':''} onClick={()=>{setFilter(v);setPage(1)}}>{n}</button>)}{sync&&<button onClick={()=>{if(executionHistory){setExecutionHistory(null);return}read<Event[]>('/sync/history').then(setExecutionHistory).catch(e=>setError(e.message))}}>{executionHistory?'收起执行记录':'全部同步执行记录'}</button>}<button onClick={()=>setRefresh(n=>n+1)}>刷新</button></div></div>
  {error&&<p role="alert">{error}</p>}
  {executionHistory&&<div className="panel ledger-grid-panel"><div className="ledger-table-wrap"><table className="ledger-detail-table"><thead><tr><th>执行时间</th><th>状态</th><th>执行汇总 · 最近 100 次</th></tr></thead><tbody>{executionHistory.map(h=><tr key={h.id}><td>{format(h.create_time)}</td><td>{names[h.status]||h.status}</td><td className="ledger-message">{syncMessage(h.message)}</td></tr>)}{!executionHistory.length&&<tr><td colSpan={3}>暂无执行记录</td></tr>}</tbody></table></div></div>}
  <div className="panel ledger-grid-panel"><div className="ledger-table-wrap"><table className="ledger-grid"><thead><tr><th>任务 / 开始时间</th><th>方式</th><th>状态</th>{(sync?['新增到 AVDB','已存在','待同步','失败 / 冲突']:['本次新增','待补抓','后续补回']).map(n=><th className="numeric" key={n}>{n}</th>)}<th>操作</th></tr></thead><tbody>
   {!data.items.length&&<tr><td colSpan={sync?8:7} className="ledger-empty">{loading?'正在读取…':'暂无任务记录'}</td></tr>}
   {data.items.map(t=><Fragment key={t.id}><tr className={expanded===t.id?'ledger-row-open':''}><td><strong>{format(t.create_time)}</strong><small>#{t.id} · {t.name}</small></td><td>{names[t.trigger]||'未记录'}</td><td><span className={'ledger-state '+((sync?syncStatus(t)==='已同步':t.status==='completed')?'done':'')}>{sync?syncStatus(t):names[t.status]||t.status}</span></td>{(sync?[t.sync.inserted||0,t.sync.existing||0,t.sync.pending||0,`${t.sync.failed||0} / ${t.sync.conflict||0}`]:[t.added,t.remaining,t.recovered]).map((n,i)=><td className="numeric" key={i}>{n}</td>)}<td><button className="ledger-detail-button" aria-expanded={expanded===t.id} onClick={()=>open(t.id)}>{expanded===t.id?'收起':'展开'}</button></td></tr>
   {expanded===t.id&&<tr className="ledger-inline-row"><td colSpan={sync?8:7}><div className="ledger-inline-detail">
    <div className="ledger-detail-meta">开始 {format(t.create_time)} · 结束 {format(t.finished_at)}{t.historical?' · 历史记录：触发方式和部分进度未记录':''}</div>
    <div className="ledger-tabs">{['板块明细','补抓记录',sync?'同步历史':'任务日志'].map(n=><button key={n} className={tab===n?'selected':''} onClick={()=>setTab(n)}>{n}</button>)}</div>
    {detailError?<p role="alert">{detailError}</p>:!detail?<p>正在读取明细…</p>:tab==='板块明细'?<><div className="ledger-table-wrap"><table className="ledger-detail-table"><thead><tr>{(sync?['板块','新增到 AVDB','已存在','待同步','失败','冲突']:['板块','扫描至页','本次新增','任务结束时失败','后续补回','待补抓','结束原因']).map(n=><th key={n}>{n}</th>)}</tr></thead><tbody>{detail.parts.map(p=><tr key={p.name}><td>{p.name}</td>{(sync?[p.sync.inserted||0,p.sync.existing||0,p.sync.pending||0,p.sync.failed||0,p.sync.conflict||0]:[p.page??'—',p.added,p.failed??'未记录',p.recovered,p.remaining,p.reason]).map((v,i)=><td key={i}>{v}</td>)}</tr>)}{!detail.parts.length&&<tr><td colSpan={sync?6:7}>尚无板块记录</td></tr>}</tbody></table></div><p className="ledger-detail-note">{sync?'按文章当前同步状态去重统计；删除暂存文章会影响当前状态数量。':'本次新增包含任务内补抓，后续额外补抓单独归回原任务。待补抓不含已忽略的记录。'}</p></>:tab==='补抓记录'?<div className="ledger-table-wrap"><table className="ledger-detail-table"><thead><tr><th>执行时间</th><th>状态</th><th>批次结果</th></tr></thead><tbody>{detail.retries.map(r=><tr key={r.id}><td>{format(r.create_time)}</td><td>{names[r.status]||r.status}</td><td className="ledger-message">{r.message}</td></tr>)}{!detail.retries.length&&<tr><td colSpan={3}>暂无可关联的补抓执行记录</td></tr>}</tbody></table></div>:tab==='同步历史'?<div className="ledger-table-wrap"><table className="ledger-detail-table"><thead><tr><th>执行时间</th><th>状态</th><th>执行汇总（可含其他任务）</th></tr></thead><tbody>{detail.history.map(h=><tr key={h.id}><td>{format(h.create_time)}</td><td>{names[h.status]||h.status}</td><td className="ledger-message">{syncMessage(h.message)}</td></tr>)}{!detail.history.length&&<tr><td colSpan={3}>暂无可关联的同步历史</td></tr>}</tbody></table></div>:<pre className="ledger-task-log">{detail.logs.length?detail.logs.map(l=>`${format(l.time)}  ${l.message}`).join('\n'):detail.message||'暂无日志'}</pre>}
   </div></td></tr>}
   </Fragment>)}
  </tbody></table></div></div>
  <div className="ledger-pagination"><span>共 {data.total} 条 · 第 {data.page} / {data.pages} 页</span><label>每页 <select aria-label="每页条数" value={size} onChange={e=>{setSize(Number(e.target.value));setPage(1)}}>{[5,10,20].map(n=><option key={n} value={n}>{n} 条</option>)}</select></label><div className="ledger-page-buttons"><button disabled={data.page<=1||loading} onClick={()=>changePage(data.page-1)}>上一页</button>{Array.from({length:data.pages},(_,i)=>i+1).filter(n=>n===1||n===data.pages||Math.abs(n-data.page)<=1).map((n,i,list)=><span key={n}>{i>0&&n-list[i-1]>1&&<span>…</span>}<button aria-current={data.page===n?'page':undefined} className={data.page===n?'selected':''} onClick={()=>changePage(n)}>{n}</button></span>)}<button disabled={data.page>=data.pages||loading} onClick={()=>changePage(data.page+1)}>下一页</button></div></div>
 </section>
}
