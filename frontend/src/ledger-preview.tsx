import { Fragment, useState } from 'react'
import './ledger-preview.css'

const examples = [
  {id: 468, time: '11/12 08:30', name: '色花堂采集', trigger: '定时', status: '已完成', added: 50, failed: 6, recovered: 3, parts: [{name:'综合讨论区',page:8,added:20,failed:2,recovered:1},{name:'转贴交流区',page:12,added:30,failed:4,recovered:2}]},
  {id: 452, time: '11/11 20:30', name: '色花堂采集', trigger: '定时', status: '已完成', added: 36, failed: 4, recovered: 4, parts: [{name:'综合讨论区',page:6,added:14,failed:1,recovered:1},{name:'转贴交流区',page:9,added:22,failed:3,recovered:3}]},
  {id: 442, time: '11/11 08:30', name: '色花堂采集', trigger: '定时', status: '已停止', added: 24, failed: 5, recovered: 2, parts: [{name:'综合讨论区',page:5,added:10,failed:2,recovered:1},{name:'转贴交流区',page:7,added:14,failed:3,recovered:1}]},
]

const tasks = Array.from({length: 48}, (_, i) => {
  const sample = examples[i % examples.length]
  const date = new Date(Date.UTC(2026, 10, 12, 0, 30) - i * 12 * 60 * 60 * 1000)
  const time = new Intl.DateTimeFormat('zh-CN', {timeZone:'Asia/Shanghai', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false}).format(date)
  return {...sample, id:468-i, time, trigger:i % 5 === 4 ? '手动' : '定时'}
})

export function LedgerPreview() {
  const [tab,setTab]=useState('采集台账')
  const [expanded,setExpanded]=useState<number|null>(null)
  const [detail,setDetail]=useState<string|null>(null)
  const [filter,setFilter]=useState('全部任务')
  const [page,setPage]=useState(1)
  const [pageSize,setPageSize]=useState(10)
  const [detailTab,setDetailTab]=useState('板块明细')
  const selected=tasks.find(t=>t.id===expanded)
  const filtered=tasks.filter(t=>filter==='全部任务'||t.trigger===filter)
  const pages=Math.max(1,Math.ceil(filtered.length/pageSize))
  const visible=filtered.slice((page-1)*pageSize,page*pageSize)
  const changePage=(next:number)=>{setPage(next);setExpanded(null);document.querySelector('.ledger-intro')?.scrollIntoView({block:'start'})}

  return <div className="shell ledger-preview">
    <aside><div className="brand"><span className="brand-icon"><img src="/shiliu-icon.png" alt="" /></span><span>拾流</span></div><div className="brand-caption">采集 · 整理 · 同步</div><nav>{['文章管理','采集任务','补抓','日志','设置'].map(n=><button className={n==='日志'?'active':''} key={n} onClick={()=>n==='日志'?null:setDetail('本页为日志台账设计预览，其他页面请在正式界面查看。')}>{n}</button>)}</nav><div className="preview-aside">本地设计预览<br/>数据均为模拟</div></aside>
    <main><div className="ledger-heading"><div><span className="ledger-eyebrow">任务记录</span><h1>日志</h1></div><span className="preview-label">模拟数据 · 不连接数据库</span></div>
      <div className="toolbar ledger-tabs">{['运行日志','采集台账','同步台账'].map(n=><button key={n} className={tab===n?'selected':''} onClick={()=>{setTab(n);setExpanded(null);setPage(1)}}>{n}</button>)}</div>
      {tab==='运行日志'?<section className="panel"><h2>运行日志</h2><pre>08:46:12　采集任务 #468 完成：新增 50 条，失败待补抓 6 条。{'\n'}08:46:15　任务 #468 同步完成：新增 48 条，已存在 2 条。{'\n'}09:05:00　任务 #468 第一轮补抓完成：恢复 3 条，等待下轮 3 条。</pre></section>:<>
      <section className="panel ledger-intro"><div><h2>{tab}</h2><p>{tab==='采集台账'?'每次任务一行，查看明细了解各板块结果。':'按来源任务归集，统计文章最终状态，重复执行不重复累计。'}</p></div><div className="ledger-filter">{['全部任务','定时','手动'].map(n=><button key={n} className={filter===n?'selected':''} onClick={()=>{setFilter(n);setPage(1);setExpanded(null)}}>{n}</button>)}</div></section>
      <section className="panel ledger-grid-panel"><div className="ledger-table-wrap"><table className="ledger-grid"><thead><tr><th>任务 / 开始时间</th><th>方式</th><th>状态</th>{(tab==='采集台账'?['新增','待补抓','补回']:['新增到 AVDB','已存在','待同步']).map(n=><th className="numeric" key={n}>{n}</th>)}<th>操作</th></tr></thead><tbody>{visible.map(t=><Fragment key={t.id}><tr className={expanded===t.id?'ledger-row-open':''}><td><strong>{t.time}</strong><small>#{t.id} · {t.name}</small></td><td>{t.trigger}</td><td><span className={'ledger-state '+(t.status==='已完成'?'done':'')}>{tab==='同步台账'?'已同步':t.status}</span></td>{(tab==='采集台账'?[t.added,t.failed,t.recovered]:[t.added-2+t.recovered,2,0]).map((n,i)=><td className="numeric" key={i}>{n}</td>)}<td><button className="ledger-detail-button" onClick={()=>{setExpanded(expanded===t.id?null:t.id);setDetailTab('板块明细')}} aria-expanded={expanded===t.id}>{expanded===t.id?'收起':'展开'}</button></td></tr>{expanded===t.id&&selected&&<tr className="ledger-inline-row"><td colSpan={7}><div className="ledger-inline-detail">      <div className="ledger-drawer-summary">{tab==='采集台账'?`本次新增 ${selected.added} 条 · 失败待补抓 ${selected.failed} 条 · 后续补回 ${selected.recovered} 条`:`累计同步 ${selected.added+selected.recovered} 条 · 失败 0 条 · 冲突 0 条`}</div>
      <div className="toolbar ledger-tabs">{['板块明细','补抓记录',tab==='采集台账'?'任务日志':'同步历史'].map(n=><button key={n} className={detailTab===n?'selected':''} onClick={()=>setDetailTab(n)}>{n}</button>)}</div>
      {detailTab==='板块明细'?<><div className="ledger-table-wrap"><table className="ledger-detail-table"><thead><tr>{(tab==='采集台账'?['板块','扫描至页','新增','待补抓','补回']:['板块','新增到 AVDB','已存在','失败','冲突']).map(n=><th key={n}>{n}</th>)}</tr></thead><tbody>{selected.parts.map(p=><tr key={p.name}><td>{p.name}</td>{(tab==='采集台账'?[p.page,p.added,p.failed,p.recovered]:[p.added-1+p.recovered,1,0,0]).map((n,i)=><td key={i}>{n}</td>)}</tr>)}<tr className="ledger-total"><td>合计</td>{(tab==='采集台账'?['—',selected.added,selected.failed,selected.recovered]:[selected.added-2+selected.recovered,2,0,0]).map((n,i)=><td key={i}>{n}</td>)}</tr></tbody></table></div><div className="ledger-detail-note">结束原因：{selected.status==='已停止'?'用户停止':'各板块连续 3 页无新增'}。<br/>任务内补抓计入本次新增，后续补回单独统计。</div></>:detailTab==='补抓记录'?<div className="ledger-table-wrap"><table className="ledger-detail-table"><thead><tr><th>轮次</th><th>本轮数量</th><th>恢复</th><th>剩余</th></tr></thead><tbody><tr><td>第一轮 · 09:05</td><td>{selected.failed}</td><td>{selected.recovered}</td><td>{selected.failed-selected.recovered}</td></tr></tbody></table><p>按原采集任务归批，未恢复的继续等待下一轮。</p></div>:detailTab==='同步历史'?<div className="ledger-table-wrap"><table className="ledger-detail-table"><thead><tr><th>时段</th><th>新增</th><th>已存在</th><th>失败</th></tr></thead><tbody><tr><td>08:30～08:35</td><td>18</td><td>0</td><td>0</td></tr><tr><td>08:35～08:40</td><td>{selected.added-20}</td><td>2</td><td>0</td></tr><tr><td>09:00～09:05 · 补抓</td><td>{selected.recovered}</td><td>0</td><td>0</td></tr></tbody></table></div>:<pre className="ledger-task-log">08:30:00　任务开始，采集综合讨论区、转贴交流区。{'\n'}08:46:12　任务结束：新增 {selected.added} 条，失败待补抓 {selected.failed} 条。{'\n'}09:05:00　第一轮额外补抓：恢复 {selected.recovered} 条。</pre>}
      
</div></td></tr>}</Fragment>)}</tbody></table></div></section>
      <div className="ledger-pagination"><span>共 {filtered.length} 条 · 第 {page} / {pages} 页</span><label>每页 <select aria-label="每页条数" value={pageSize} onChange={e=>{setPageSize(Number(e.target.value));setPage(1);setExpanded(null)}}>{[5,10,20].map(n=><option key={n} value={n}>{n} 条</option>)}</select></label><div className="ledger-page-buttons"><button disabled={page===1} onClick={()=>changePage(page-1)}>上一页</button>{Array.from({length:pages},(_,i)=>i+1).filter(n=>n===1||n===pages||Math.abs(n-page)<=1).map((n,i,list)=><span key={n}>{i>0&&n-list[i-1]>1&&<span className="ledger-ellipsis">…</span>}<button aria-label={`第 ${n} 页`} aria-current={page===n?'page':undefined} className={page===n?'selected':''} onClick={()=>changePage(n)}>{n}</button></span>)}<button disabled={page===pages} onClick={()=>changePage(page+1)}>下一页</button></div></div>
      <p className="ledger-note">预览中的时间、任务与数量均为示例，正式接入后按实际入库结果统计。</p></>}
    </main>{detail&&<div className="ledger-overlay" onClick={()=>setDetail(null)}><section className="panel" onClick={e=>e.stopPropagation()}><div className="toolbar"><h2>记录详情</h2><button onClick={()=>setDetail(null)}>关闭</button></div><pre>{detail}</pre></section></div>}
  </div>
}
