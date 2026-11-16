import { Fragment, useEffect, useState, useRef } from 'react'
import { createRoot } from 'react-dom/client'
import './collector.css'
import { Ledger } from './ledger'
import { AvdbSearch } from './avdb-search'
import { AvdbSettings } from './avdb-settings'
import { PushRecords } from './push-records'
import { ImagePreview } from './image-preview'
import './mobile.css'
import { PushToasts } from './push-toast'
import './theme.css'
async function api(path: string, body?: unknown, method?: string) {
  const r = await fetch('/api' + path, {
    method: method ?? (body === undefined ? 'GET' : 'POST'),
    headers:
      body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  })
  if (!r.ok) {
    let detail
    try {
      detail = (await r.json()).detail
    } catch {
      detail = r.statusText
    }
    throw Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return r.json()
}
const logWords: Record<string, string> = {
  crawl: '采集',
  file: 'CSV 导入',
  legacy: '旧库导入',
  merge: '转换同步',
  cleanup: '数据清理',
  running: '运行中',
  completed: '已完成',
  stopped: '已停止',
  failed: '失败',
  interrupted: '已中断',
  inserted: '新增',
  existing: '已存在',
  skipped: '跳过',
  conflict: '冲突',
  errors: '错误详情',
  row: '行号',
  error: '错误',
  batch_id: '批次',
  id: '编号',
  batch: '批次',
  create_time: '记录时间',
  message: '说明',
  realtime: '实时同步',
  scheduled: '定时同步',
  operation: '操作',
  total: '文章数',
  stats: '统计',
  runs: '同步次数',
  window: '汇总时段起点',
}
function chineseLog(value: unknown): string {
  if (typeof value === 'string') {
    try {
      return chineseLog(JSON.parse(value))
    } catch {
      return logWords[value] ?? value
    }
  }
  if (Array.isArray(value)) return value.map(chineseLog).join('\n')
  if (value && typeof value === 'object')
    return Object.entries(value)
      .filter(([key, val]) => !(key === 'errors' && Array.isArray(val) && !val.length))
      .map(([key, val]) => key === 'window' && typeof val === 'string'
        ? `汇总时段：${new Date(val).toLocaleString()} ～ ${new Date(new Date(val).getTime() + 5 * 60 * 1000).toLocaleTimeString()}`
        : `${logWords[key] ?? key}：${chineseLog(val)}`)
      .join('；')
  return String(value ?? '无')
}
type Row = {
  id: number
  tid: number
  title: string
  section: string
  website: string
  source: string
  merge_status: string
  magnet: string[]
  edk: string[]
  preview_images: string[]
  error: string
  batch_id: number
}
type Overview = {
  phase?: string
  sync_queued?: number
  total: number
  pending: number
  active: number | null
  sections: Record<string, string>
  groups: { section: string; source: string; count: number }[]
  batches: { id: number; kind: string; status: string; message: string }[]
}
function App() {
  const [theme,setTheme]=useState<'light'|'dark'|'system'>('system')
  const [themeSaving,setThemeSaving]=useState(false)
  const [dark,setDark]=useState(()=>window.matchMedia('(prefers-color-scheme: dark)').matches)
  useEffect(()=>{let alive=true;api('/avdb/theme').then(r=>{if(alive&&['light','dark','system'].includes(r.theme))setTheme(r.theme)}).catch(()=>{});return()=>{alive=false}},[])
  useEffect(()=>{
    const media=window.matchMedia('(prefers-color-scheme: dark)')
    const apply=()=>{const enabled=theme==='dark'||theme==='system'&&media.matches;setDark(enabled);document.documentElement.dataset.theme=enabled?'dark':'light';document.documentElement.style.colorScheme=enabled?'dark':'light';document.querySelector('meta[name="theme-color"]')?.setAttribute('content',enabled?'#141d21':'#f3f5f7')}
    apply();media.addEventListener('change',apply);return()=>media.removeEventListener('change',apply)
  },[theme])
  const toggleTheme=async()=>{const next=dark?'light':'dark';setThemeSaving(true);try{await api('/avdb/theme',{theme:next});setTheme(next)}catch(e){setError((e as Error).message)}finally{setThemeSaving(false)}}
  const [mobileNavVisible, setMobileNavVisible] = useState(true)
  useEffect(() => {
    let previous = window.scrollY
    let accumulated = 0
    const onScroll = () => {
      const current = Math.max(0, window.scrollY)
      const delta = current - previous
      if (Math.sign(delta) !== Math.sign(accumulated)) accumulated = 0
      accumulated += delta
      if (current < 32) setMobileNavVisible(true)
      else if (Math.abs(accumulated) > 12) setMobileNavVisible(accumulated < 0)
      previous = current
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
  const csvInput = useRef<HTMLInputElement>(null)
  const [taskTab, setTaskTab] = useState('采集配置')
  const [settingsTab, setSettingsTab] = useState('连接与推送')

  const [retryLinks,setRetryLinks]=useState<{tid:number;detail_url:string;title:string|null;magnet:string[];edk:string[]}|null>(null)
  const [retryExpanded,setRetryExpanded]=useState<number|null>(null)
  const [retryDetailError,setRetryDetailError]=useState('')
  const [retryDetailLoading,setRetryDetailLoading]=useState(false)
  const retryRequest=useRef(0)
  const toggleRetry=(id:number)=>{
    const request=++retryRequest.current
    if(retryExpanded===id){setRetryExpanded(null);return}
    setRetryExpanded(id);setRetryLinks(null);setRetryDetailError('');setRetryDetailLoading(true)
    api(`/retries/${id}/links`).then(r=>{if(retryRequest.current===request)setRetryLinks(r)}).catch(e=>{if(retryRequest.current===request)setRetryDetailError(e.message)}).finally(()=>{if(retryRequest.current===request)setRetryDetailLoading(false)})
  }
  const [retryStatus,setRetryStatus]=useState('waiting')
  const [retryAutoEnabled,setRetryAutoEnabled]=useState<boolean|null>(null)
  const [retrySettingsSaving,setRetrySettingsSaving]=useState(false)
  const saveRetryAuto=async(enabled:boolean)=>{
    setRetrySettingsSaving(true)
    try {const r=await api('/retries/settings',{auto_enabled:enabled});setRetryAutoEnabled(r.auto_enabled)}catch(e){setError((e as Error).message)}finally{setRetrySettingsSaving(false)}
  }
  const [retryRows,setRetryRows]=useState<{id:number;tid:number;section:string;status:string;auto_attempts:number;manual_attempts:number;error:string;next_run:string|null}[]>([])
  const [retryTotal,setRetryTotal]=useState(0)
  const [retryPage,setRetryPage]=useState(1)
  useEffect(()=>{retryRequest.current++;setRetryExpanded(null);setRetryLinks(null)},[retryStatus,retryPage])
  const [retrySelected,setRetrySelected]=useState<number[]>([])
  const [retryAll,setRetryAll]=useState(false)
  const loadRetries=async()=>{const r=await api(`/retries?status=${retryStatus}&page=${retryPage}`);setRetryRows(r.items);setRetryTotal(r.total)}
  const retryAction=async(action:string)=>{
    if(!retryAll&&!retrySelected.length){setError('请先选择记录');return}
    if(!confirm(`确认${action==='delete'?'删除补抓记录（不删除文章）':action==='ignore'?'忽略':action==='restart'?'重置自动补抓次数':'手动补抓'} ${retryAll?retryTotal:retrySelected.length} 条？`))return
    try {await api('/retries/action',{action,ids:retryAll?null:retrySelected,status:retryAll?retryStatus:null});setRetrySelected([]);await loadRetries()}catch(e){setError((e as Error).message)}
  }
  const [logTab, setLogTab] = useState('运行日志')
  useEffect(()=>{const open=()=>{setPage('日志');setLogTab('推送记录');setMobileNavVisible(true)};window.addEventListener('shiliu:open-push-records',open);return()=>window.removeEventListener('shiliu:open-push-records',open)},[])
  const [statusFilter, setStatusFilter] = useState('')
  const [allFiltered, setAllFiltered] = useState(false)
  const [resolution, setResolution] = useState<{operation: string; filters: unknown; confirmation: string; items: {id: number; tid: number; title: string; size: number | null; target_tid: number; available: boolean; existing_title: string | null; existing_website: string | null}[]} | null>(null)
  const prepareResolution = async (operation: string) => {
    try {
      if (!allFiltered && !selected.length) throw Error("请先勾选文章，或选择筛选全部")
      const scope = filters()
      const result = await api('/resolve/preview', {operation, filters: scope})
      setResolution({...result, operation, filters: scope})
    } catch (e) { setError((e as Error).message) }
  }
  const [syncProgress, setSyncProgress] = useState<{running: boolean; processed: number; total: number; stats: Record<string, number>; error: string | null} | null>(null)
  const [runtimeLogs, setRuntimeLogs] = useState('')
  const [autoLogs, setAutoLogs] = useState(true)
  const loadRuntimeLogs = async () => {
    const entries: { time: string; level: string; icon: string; message: string }[] = await api('/runtime-logs')
    setRuntimeLogs([...entries].reverse().map((entry) =>
      `${new Date(entry.time).toLocaleString()} | ${entry.icon} ${entry.level}\n${entry.icon} ${entry.message}`,
    ).join('\n'))
  }
  const [editing, setEditing] = useState<number | null>(null)
  const [defaultHome,setDefaultHome]=useState('文章管理')
  const homeNavigationChanged=useRef(false)
  useEffect(()=>{let alive=true;const load=async()=>{let saved=await api('/avdb/preferences');let legacy:string|null=null;try{legacy=localStorage.getItem('shiliu.defaultHome')}catch{}
   if(!saved.configured&&legacy&&['文章管理','AVDB 搜索','采集任务','日志','设置'].includes(legacy))saved=await api('/avdb/preferences',{default_home:legacy,only_if_absent:true});
   if(legacy){try{localStorage.removeItem('shiliu.defaultHome')}catch{}}
   if(alive){setDefaultHome(saved.default_home);if(!new URLSearchParams(window.location.search).get('page')&&!homeNavigationChanged.current)setPage(saved.default_home)}
  };load().catch(()=>{if(alive)setError('无法读取数据库中的首页设置')});return()=>{alive=false}},[])
  const [homeSaved,setHomeSaved]=useState(false)
  const [page, setPage] = useState(()=>{const explicit=new URLSearchParams(window.location.search).get('page');const names:Record<string,string>={avdb:'AVDB 搜索',articles:'文章管理',tasks:'采集任务',logs:'日志',settings:'设置'};if(explicit&&names[explicit])return names[explicit];return ['文章管理','AVDB 搜索','采集任务','日志','设置'].includes(defaultHome)?defaultHome:'文章管理'}),
    [overview, setOverview] = useState<Overview>({
      total: 0,
      pending: 0,
      active: null,
      sections: {},
      groups: [],
      batches: [],
    }),
    [rows, setRows] = useState<Row[]>([]),
    [total, setTotal] = useState(0),
    [num, setNum] = useState(1),
    [section, setSection] = useState(''),
    [keyword, setKeyword] = useState(''),
    [selected, setSelected] = useState<number[]>([]),
    [detail, setDetail] = useState<Row | null>(null),
    [detailPreview, setDetailPreview] = useState<number | null>(null),
    [output, setOutput] = useState(''),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [plans, setPlans] = useState<
      {
        id: number
        name: string
        params: Record<string, unknown>
        cron: string
        enabled: boolean
      }[]
    >([]),
    [name, setName] = useState('色花堂采集'),
    [boards, setBoards] = useState<string[]>(['95', '142']),
    [start, setStart] = useState(1),
    [end, setEnd] = useState(''),
    [emptyPages, setEmptyPages] = useState(3),
    [cron, setCron] = useState(''),
    [enabled, setEnabled] = useState(false),
    [network, setNetwork] = useState({
      PROXY: '',
      FLARE_SOLVERR_URL: '',
      database: '',
      target: '',
    }),
    [cleanOpen, setCleanOpen] = useState(false),
    [cleanSections, setCleanSections] = useState<string[]>([]),
    [syncSettings, setSyncSettings] = useState({
      mode: 'realtime',
      cron: '0 * * * *',
      fallback_minutes: 15,
    }),
    [cleanup, setCleanup] = useState<{
      count: number
      confirmation: string
      sections: string[]
    } | null>(null)
  useEffect(()=>{if(page!=='采集任务'||taskTab!=='失败补抓')return;loadRetries().catch(e=>setError(e.message));const timer=setInterval(()=>loadRetries().catch(()=>{}),5000);return()=>clearInterval(timer)},[page,taskTab,retryStatus,retryPage])
  useEffect(()=>{if(page==='采集任务'&&taskTab==='失败补抓')api('/retries/settings').then(r=>setRetryAutoEnabled(r.auto_enabled)).catch(e=>setError(e.message))},[page,taskTab])
  useEffect(()=>{if(page==='设置'&&settingsTab==='采集网络')api('/settings').then(setNetwork).catch(e=>setError(e.message))},[page,settingsTab])
  const filters = () => ({
    merge_status: statusFilter || null,
    section: section || null,
    keyword: keyword || null,
    ids: !allFiltered && selected.length ? selected : null,
  })
  const cleanFilters = () => ({ sections: cleanSections })
  const refresh = async () => {
    const [o, a, t, n] = await Promise.all([
      api('/overview'),
      api('/articles/search?page=' + num, {
        merge_status: statusFilter || null,
        section: section || null,
        keyword: keyword || null,
      }),
      api('/tasks'),
      api('/settings'),
    ])
    setOverview(o)
    setRows(a.items)
    setTotal(a.total)
    setPlans(t)
    setNetwork(n)
    setSyncSettings(await api('/sync/settings'))
  }
  useEffect(() => {
    if(page==='AVDB 搜索'||(page==='设置'&&new URLSearchParams(window.location.search).get('page')==='avdb'))return
    refresh().catch((e) => setError(e.message))
  }, [num, section, statusFilter,page])
  useEffect(() => {
    if(page==='AVDB 搜索'||(page==='设置'&&new URLSearchParams(window.location.search).get('page')==='avdb'))return
    const timer = setInterval(() => {
      api('/sync/status').then(setSyncProgress).catch(() => {})
      api('/overview')
        .then(setOverview)
        .catch(() => {})
    }, 4000)
    return () => clearInterval(timer)
  }, [page])
  const action = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError('')
    try {
      const result = await fn()
      if (result !== undefined) setOutput(JSON.stringify(result, null, 2))
      if(!(page==='设置'&&new URLSearchParams(window.location.search).get('page')==='avdb'))await refresh()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  useEffect(() => {
    if (page !== '日志' || logTab !== '运行日志') return
    let disposed = false
    const load = () => loadRuntimeLogs().catch((e) => { if (!disposed) setError(e.message) })
    load()
    const timer = autoLogs ? setInterval(load, 3000) : undefined
    return () => { disposed = true; clearInterval(timer) }
  }, [page, logTab, autoLogs])
  const plan = () => ({
    name,
    section_id_list: boards,
    start_page: start,
    max_page: end ? Number(end) : null,
    stop_after_empty_pages: emptyPages,
    cron: cron || null,
    enabled,
  })
  return (
    <div className="shell">
      <PushToasts />
      <aside className={mobileNavVisible ? 'mobile-nav-visible' : 'mobile-nav-hidden'}>
        <div className="brand"><span className="brand-icon"><img src="/shiliu-icon.png" alt="" /></span><span>拾流</span></div>
        <div className="brand-caption">采集 · 整理 · 同步</div>
        <nav>
          {['文章管理', 'AVDB 搜索', '采集任务', '日志', '设置'].map((p) => (
            <button
              className={page === p ? 'active' : ''}
              key={p}
              onClick={() => {
                setMobileNavVisible(true)
                homeNavigationChanged.current=true
                setPage(p)
                setOutput('')
                setError('')
              }}
            >
              <span className="mobile-nav-icon" aria-hidden="true"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={({'文章管理':'M5 3h14v18H5z M8 7h8 M8 11h8 M8 15h5','AVDB 搜索':'M21 21l-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0','采集任务':'M8 3h8v4H8z M6 5H4v16h16V5h-2 M8 12h8 M8 16h5','日志':'M5 3h14v18H5z M8 8h8 M8 12h8 M8 16h8','设置':'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2'} as Record<string,string>)[p]}/></svg></span><span>{p}</span>
            </button>
          ))}
        </nav>
      </aside>
      <main className={page==='文章管理'?'compact-articles':page==='采集任务'?'compact-tasks':undefined}>
        <header>
          <div>
            <h1>{page}</h1>
            <p className="page-caption">
              {
                (
                  {
                    文章管理: '一处整理采集所得，让每条资源各归其位。',
                    'AVDB 搜索': '',
                    采集任务: '按计划巡访，循新帖而来。',
                    日志: '每一次采集，都有迹可循。',
                    设置: '调好连接与节奏，余下交给采集。',
                  } as Record<string, string>
                )[page]
              }
            </p>
          </div>
          <button className="theme-toggle" disabled={themeSaving} onClick={()=>void toggleTheme()} aria-label={dark?'切换到日间模式':'切换到夜间模式'} title={dark?'切换到日间模式':'切换到夜间模式'}><svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{dark?<><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/></>:<path d="M20.5 13a8.5 8.5 0 0 1-9.5-9.5A8.5 8.5 0 1 0 20.5 13Z"/>}</svg></button>
        </header>
        {page === 'AVDB 搜索' && <AvdbSearch />}
        {page === '采集任务' && (
          <div className="subnav">
            {['采集配置', '定时计划', '失败补抓'].map((t) => (
              <button
                key={t}
                className={taskTab === t ? 'selected' : ''}
                onClick={() => {
                  setTaskTab(t)
                  setOutput('')
                }}
              >
                {t}
              </button>
            ))}
          </div>
        )}
        {page === '设置' && (
          <div className="subnav">
            {['连接与推送', '采集网络', '同步策略', '界面偏好'].map((t) => (
              <button
                key={t}
                className={settingsTab === t ? 'selected' : ''}
                onClick={() => {
                  setSettingsTab(t)
                  setOutput('')
                }}
              >
                {t}
              </button>
            ))}
          </div>
        )}
        {page === '日志' && (
          <div className="subnav">
            {['运行日志', '采集台账', '同步台账', '推送记录'].map((t) => (
              <button
                key={t}
                className={logTab === t ? 'selected' : ''}
                onClick={() => setLogTab(t)}
              >
                {t}
              </button>
            ))}
          </div>
        )}
        {page === '文章管理' && (
          <div className="stats">
            <div>
              <small>暂存文章</small>
              <strong>{overview.total}</strong>
            </div>
            <div>
              <small>待同步</small>
              <strong>{overview.pending}</strong>
            </div>
            <div>
              <small>采集状态</small>
              <strong>
                {overview.active ? (overview.phase === 'syncing' ? '采集完成 · 同步收尾中' : overview.phase === 'retrying' ? '补抓中 #' + overview.active : '采集中 #' + overview.active) : '空闲'}
              </strong>
            </div>
            <div>
              <small>同步状态</small>
              <strong>{overview.sync_queued ? `同步排队 ${overview.sync_queued} 批` : syncProgress?.running ? '同步中' : '空闲'}</strong>
            </div>
          </div>
        )}
        {error && <div className="error">{error}</div>}
        {page === '文章管理' && (
          <>
        <section className="panel sync-card"><div className="toolbar"><h2>同步动态</h2><button onClick={() => {setPage('日志');setLogTab('同步台账')}}>查看历史</button></div>                {syncProgress && (syncProgress.running || syncProgress.total > 0 || syncProgress.error) && (
                  <span role="status">
                    {syncProgress.running ? '同步中' : '同步结束'}：{syncProgress.processed}/{syncProgress.total}
                    {' · '}{chineseLog(syncProgress.stats)}
                    {syncProgress.error && ` · ${syncProgress.error}`}
                  </span>
                )}
{!syncProgress?.total && <p>{overview.sync_queued ? '等待后台同步队列' : '暂无正在执行的同步任务'}</p>}</section>
            <div className="status-tabs">
              {Object.entries({'':'全部',pending:'待同步',failed:'失败',conflict:'冲突',inserted:'已新增',existing:'已存在'}).map(([value,label]) => <button key={value} className={statusFilter === value ? 'active' : ''} onClick={() => {setStatusFilter(value);setSelected([]);setAllFiltered(false);setNum(1)}}>{label}</button>)}
            </div>
            <section className="panel article-panel">
              <div className="toolbar article-tools">
                <button
                  disabled={busy}
                  onClick={() => csvInput.current?.click()}
                >
                  导入 CSV
                </button>
                <span className="file-input-holder">
                  <input
                    ref={csvInput}
                    style={{ display: 'none' }}
                    type="file"
                    accept=".csv"
                    disabled={busy}
                    onChange={(e) => {
                      const file = e.target.files?.[0]
                      if (file) {
                        const form = new FormData()
                        form.append('file', file)
                        action(() => api('/import/file', form))
                        e.target.value = ''
                      }
                    }}
                  />
                </span>
                <button
                  onClick={async () => {
                    try {
                      const r = await fetch('/api/export', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(filters()),
                      })
                      if (!r.ok) throw Error('导出失败')
                      const u = URL.createObjectURL(await r.blob())
                      const a = document.createElement('a')
                      a.href = u
                      a.download = 'shiliu-articles.csv'
                      a.click()
                      URL.revokeObjectURL(u)
                    } catch (e) {
                      setError((e as Error).message)
                    }
                  }}
                >
                  {selected.length ? '导出选中项' : '导出 CSV'}
                </button>
                <details className="more-actions"><summary>更多操作</summary><button className="danger" onClick={() => {setCleanOpen(true);setCleanup(null);setCleanSections([])}}>清理板块</button></details>
              </div>
              <div className="toolbar">
                <input
                  placeholder="搜索"
                  value={keyword}
                  onChange={(e) => setKeyword(e.target.value)}
                />
                <select
                  value={section}
                  onChange={(e) => {
                    setSection(e.target.value)
                    setAllFiltered(false)
                    setSelected([])
                    setNum(1)
                  }}
                >
                  <option value="">全部板块</option>
                  {Array.from(
                    new Set(overview.groups.filter((g) => g.count > 0).map((g) => g.section)),
                  ).map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </select>
                <button
                  onClick={() => {
                    setSelected([])
                    action(refresh)
                  }}
                >
                  搜索
                </button>
              </div>
              <div className="toolbar batch-actions">
                {["pending", "failed", "conflict"].includes(statusFilter) && <>
                <button
                  className="primary"
                  disabled={busy || syncProgress?.running || statusFilter === 'conflict'}
                  onClick={() => {
                    if (
                      confirm(
                        `合并${selected.length ? '选中 ' + selected.length + ' 条' : '当前筛选范围内的全部'}资源到 Avdb 主表？已有记录不会覆盖。`,
                      )
                    )
                      action(() => api('/merge', filters()))
                  }}
                >
                  {statusFilter === 'failed' ? '重试同步' : statusFilter === 'conflict' ? '等待手动处理' : '同步待处理'}
                </button>
                <label><input type="checkbox" checked={allFiltered} onChange={(e) => {setAllFiltered(e.target.checked);setSelected([])}} />选择筛选全部（{total} 条）</label>
                {statusFilter === 'failed' && <button disabled={busy || syncProgress?.running} onClick={() => prepareResolution('clear_size')}>大小留空并同步</button>}
                {statusFilter === 'conflict' && <button disabled={busy || syncProgress?.running} onClick={() => prepareResolution('resolve_conflict')}>使用备用 TID 同步</button>}
                </>}
                <span>
                  {selected.length
                    ? `已选 ${selected.length} 条`
                    : `当前筛选 ${total.toLocaleString()} 条` }
                </span>
              </div>
              <div className="table-wrap article-table">
                <table>
                  <thead>
                    <tr>
                      <th></th>
                      <th>原帖 / 标题</th>
                      <th>板块</th>
                      <th>链接</th>
                      <th>同步状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((a) => (
                      <tr key={a.id}>
                        <td>
                          <input
                            type="checkbox"
                            checked={selected.includes(a.id)}
                            onChange={(e) =>
                              setSelected(
                                e.target.checked
                                  ? [...selected, a.id]
                                  : selected.filter((x) => x !== a.id),
                              )
                            }
                          />
                        </td>
                        <td>
                          <small>#{a.tid}</small>
                          <button
                            className="text-button"
                            onClick={() => setDetail(a)}
                          >
                            {a.title}
                          </button>
                        </td>
                        <td>{a.section}</td>
                        <td>
                          磁力 {a.magnet?.length ?? 0}
                          <br />
                          ED2K {a.edk?.length ?? 0}
                        </td>
                        <td>
                          <span className={'badge ' + a.merge_status}>
                            {(
                              {
                                pending: '待同步',
                                inserted: '已新增',
                                existing: '已存在',
                                failed: '失败',
                                conflict: '冲突',
                              } as Record<string, string>
                            )[a.merge_status] ?? a.merge_status}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!rows.length && (
                  <div className="empty">
                    暂无文章，可导入 CSV 或开始采集。
                  </div>
                )}
              </div>
              <div className="toolbar footer">
                <span>
                  共 {total} 条 · 第 {num} 页
                </span>
                <button
                  disabled={num <= 1}
                  onClick={() => {
                    setNum(num - 1)
                    setSelected([])
                  }}
                >
                  上一页
                </button>
                <button
                  disabled={num * 30 >= total}
                  onClick={() => {
                    setNum(num + 1)
                    setSelected([])
                  }}
                >
                  下一页
                </button>
              </div>
            </section>
          </>
        )}
        {page==='采集任务'&&taskTab==='失败补抓'&&<section className="panel retry-panel">
          <h2>失败补抓</h2>
          <label><input type="checkbox" role="switch" checked={retryAutoEnabled===true} disabled={retryAutoEnabled===null||retrySettingsSaving} onChange={e=>saveRetryAuto(e.target.checked)}/>额外三次自动补抓{retrySettingsSaving?'（保存中…）':retryAutoEnabled===null?'（读取中…）':''}</label>
          <p>默认开启，额外自动补抓最多三次，仍失败后转手动。关闭后暂停自动补抓，保留队列和次数，仍可手动补抓；重新开启后继续处理。正在抓取的单条帖子会完成。数据库恢复不消耗补抓次数。</p>
          <div className="status-tabs">{Object.entries({waiting:'自动等待',running:'补抓中',manual:'待手动补抓',recovered:'已恢复',ignored:'已忽略'}).map(([v,l])=><button key={v} className={retryStatus===v?'active':''} onClick={()=>{setRetryStatus(v);setRetryPage(1);setRetrySelected([]);setRetryAll(false)}}>{l}</button>)}</div>
          {retryStatus!=='running'&&<div className="toolbar"><label><input type="checkbox" checked={retryAll} onChange={e=>{setRetryAll(e.target.checked);setRetrySelected([])}}/>选择筛选全部（{retryTotal}）</label>
          {['waiting','manual'].includes(retryStatus)&&<button onClick={()=>retryAction('run')}>手动补抓</button>}
          <button onClick={()=>retryAction('restart')}>重新开启自动补抓</button><button onClick={()=>retryAction('ignore')}>忽略</button><button className="danger" onClick={()=>retryAction('delete')}>删除记录</button></div>}
          <div className="table-wrap"><table className="retry-table retry-compact"><thead><tr><th></th><th>帖子 / 板块</th><th>自动 / 手动</th><th>最近原因</th><th>下次执行</th></tr></thead><tbody>{retryRows.map(r=><Fragment key={r.id}><tr className={`retry-click-row ${retryExpanded===r.id?'ledger-row-open':''}`} tabIndex={0} aria-expanded={retryExpanded===r.id} aria-label={`帖子 ${r.tid} 补抓明细`} onClick={()=>toggleRetry(r.id)} onKeyDown={e=>{if(e.target===e.currentTarget&&(e.key==='Enter'||e.key===' ')){e.preventDefault();toggleRetry(r.id)}}}><td onClick={e=>e.stopPropagation()}><input type="checkbox" disabled={r.status==='running'||retryAll} checked={retryAll||retrySelected.includes(r.id)} onChange={e=>setRetrySelected(e.target.checked?[...retrySelected,r.id]:retrySelected.filter(i=>i!==r.id))}/></td><td><span className="retry-post-line"><span>#{r.tid}</span><span className="retry-section">{r.section}</span></span></td><td data-label="自动 / 手动次数">{r.auto_attempts} / {r.manual_attempts}</td><td data-label="最近原因">{r.error||'—'}</td><td data-label="下次执行">{r.next_run?new Date(r.next_run).toLocaleString():'—'}</td></tr>
          {retryExpanded===r.id&&<tr className="retry-inline-row"><td colSpan={5}><div className="retry-inline-detail"><div className="toolbar"><strong>#{r.tid} · {r.section}</strong><a href={`https://sehuatang.org/thread-${r.tid}-1-2.html`} target="_blank" rel="noreferrer">查看原帖</a></div>{retryDetailLoading?<p>正在读取链接…</p>:retryDetailError?<p role="alert">{retryDetailError}</p>:retryLinks&&<><p>{retryLinks.title||'暂未采集入库'}</p><div className="retry-link-group"><h3>磁力（{retryLinks.magnet.length}）</h3><pre>{retryLinks.magnet.join('\n\n')||'无'}</pre><h3>ED2K（{retryLinks.edk.length}）</h3><pre>{retryLinks.edk.join('\n\n')||'无'}</pre></div>{(retryLinks.magnet.length>0||retryLinks.edk.length>0)&&<button onClick={()=>navigator.clipboard.writeText([...retryLinks.magnet,...retryLinks.edk].join('\n')).catch(()=>setError('当前浏览器无法复制，请长按链接手动复制'))}>复制全部链接</button>}</>}</div></td></tr>}
          </Fragment>)}</tbody></table></div>
          {!retryRows.length&&<p>暂无记录</p>}<div className="toolbar"><span>共 {retryTotal} 条 · 第 {retryPage} 页</span><button disabled={retryPage<=1} onClick={()=>{setRetryPage(retryPage-1);setRetrySelected([])}}>上一页</button><button disabled={retryPage*50>=retryTotal} onClick={()=>{setRetryPage(retryPage+1);setRetrySelected([])}}>下一页</button></div>
        </section>}
        {page === '采集任务' && (
          <>
            {taskTab === '采集配置' && (
              <section className="panel">
                <h2>色花堂采集</h2>
                <p>
                  不填写结束页：连续指定页数没有成功新增文章后停止，最多扫描 100 页。填写结束页：按指定范围扫描。失败帖子交给补抓。
                </p>
                <label>
                  任务名称
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <div className="boards">
                  {Object.entries(overview.sections).map(([id, label]) => (
                    <label key={id}>
                      <input
                        type="checkbox"
                        checked={boards.includes(id)}
                        onChange={(e) =>
                          setBoards(
                            e.target.checked
                              ? [...boards, id]
                              : boards.filter((x) => x !== id),
                          )
                        }
                      />
                      {label} <small>{id}</small>
                    </label>
                  ))}
                </div>
                <div className="grid">
                  <label>
                    起始页
                    <input
                      type="number"
                      min="1"
                      value={start}
                      onChange={(e) => setStart(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    结束页（空为智能）
                    <input
                      type="number"
                      min={start}
                      value={end}
                      onChange={(e) => setEnd(e.target.value)}
                    />
                  </label>
                  <label>
                    连续无新增页数（智能模式）
                    <input type="number" min="1" max="100" disabled={!!end} value={emptyPages} onChange={(e) => setEmptyPages(Number(e.target.value))} />
                  </label>
                  <label>
                    定时 Cron（可选）
                    <input
                      placeholder="0 3 * * *"
                      value={cron}
                      onChange={(e) => setCron(e.target.value)}
                    />
                  </label>
                </div>
                <label>
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => setEnabled(e.target.checked)}
                  />
                  启用定时计划
                </label>
                <div className="toolbar">
                  <button
                    className="primary"
                    disabled={busy || !!overview.active || !boards.length}
                    onClick={() => action(() => api('/tasks/run', plan()))}
                  >
                    立即采集
                  </button>
                  <button
                    disabled={busy || !boards.length}
                    onClick={() =>
                      action(() =>
                        api(
                          editing ? '/tasks/' + editing : '/tasks',
                          plan(),
                          editing ? 'PUT' : 'POST',
                        ),
                      )
                    }
                  >
                    {editing ? '更新计划' : '保存计划'}
                  </button>
                  <button
                    className="danger"
                    disabled={!overview.active}
                    onClick={() => action(() => api('/tasks/stop', {}))}
                  >
                    停止当前任务
                  </button>
                </div>
                <p>停止会等待当前请求返回，已保存数据保留，不自动合并。</p>
              </section>
            )}
            {taskTab === '定时计划' && (
              <section className="panel">
                <h2>定时计划</h2>
                {plans.map((t) => (
                  <div className="list-row" key={t.id}>
                    <div>
                      <strong>{t.name}</strong>
                      <p>
                        {t.cron || '手动'} · {t.enabled ? '已启用' : '未启用'} ·{' '}
                        {((t.params.section_id_list as string[]) || []).map(id=>overview.sections[id] || id).join('、')} · 第 {String(t.params.start_page || 1)} 页起 · {t.params.max_page ? `至 ${t.params.max_page} 页` : `连续 ${t.params.stop_after_empty_pages || 3} 页无新增停止`}
                      </p>
                    </div>
                    <button
                      onClick={() => {
                        setEditing(t.id)
                        setName(t.name)
                        setBoards((t.params.section_id_list as string[]) || [])
                        setStart(Number(t.params.start_page) || 1)
                        setEmptyPages(Number(t.params.stop_after_empty_pages) || 3)
                        setEnd(
                          t.params.max_page ? String(t.params.max_page) : '',
                        )
                        setCron(t.cron || '')
                        setEnabled(t.enabled)
                        setTaskTab('采集配置')
                      }}
                    >
                      编辑
                    </button>{' '}
                    <button
                      disabled={!!overview.active}
                      onClick={() =>
                        action(() =>
                          api('/tasks/run', { name: t.name, ...t.params }),
                        )
                      }
                    >
                      执行
                    </button>
                    <button
                      onClick={() => {
                        if (confirm('删除该采集计划？'))
                          action(() =>
                            api('/tasks/' + t.id, undefined, 'DELETE'),
                          )
                      }}
                    >
                      删除
                    </button>
                  </div>
                ))}
              </section>
            )}
          </>
        )}
        {page === '设置' && settingsTab === '连接与推送' && <AvdbSettings />}
        {page === '设置' && settingsTab === '采集网络' && (
          <section className="panel">
            <h2>采集网络</h2>
            <p className="connection-status">
              数据库由部署环境配置 · 同步目标：Avdb article
            </p>{' '}
            <label>
              代理地址
              <input
                value={network.PROXY}
                onChange={(e) =>
                  setNetwork({ ...network, PROXY: e.target.value })
                }
                placeholder="http://主机:端口"
              />
            </label>
            <label>
              FlareSolverr 地址
              <input
                value={network.FLARE_SOLVERR_URL}
                onChange={(e) =>
                  setNetwork({ ...network, FLARE_SOLVERR_URL: e.target.value })
                }
                placeholder="http://主机:8191"
              />
            </label>
            <button
              className="primary"
              disabled={busy}
              onClick={() =>
                action(() =>
                  api('/settings', {
                    PROXY: network.PROXY,
                    FLARE_SOLVERR_URL: network.FLARE_SOLVERR_URL,
                  }),
                )
              }
            >
              保存网络设置
            </button>
          </section>
        )}
        {page === '设置' && settingsTab === '界面偏好' && <section className="panel avdb-settings"><h2>默认首页</h2><label>打开地址时进入<select value={defaultHome} onChange={e=>{setDefaultHome(e.target.value);setHomeSaved(false)}}>{['文章管理','AVDB 搜索','采集任务','日志','设置'].map(name=><option key={name}>{name}</option>)}</select></label><p>保存到拾流数据库，所有设备共用。地址中指定的页面优先。</p><button className="primary" onClick={()=>{api('/avdb/preferences',{default_home:defaultHome}).then(()=>setHomeSaved(true)).catch(e=>setError(e.message))}}>保存首页设置</button>{homeSaved&&<p role="status">默认首页已保存</p>}</section>}
        {page === '设置' && settingsTab === '同步策略' && (
          <section className="panel">
            <h2>同步策略</h2>

            <div className="mode-options">
              <button
                className={syncSettings.mode === 'realtime' ? 'primary' : ''}
                onClick={() =>
                  setSyncSettings({ ...syncSettings, mode: 'realtime' })
                }
              >
                实时同步<span>爬取新增入库后触发，没有新增不运行</span>
              </button>
              <button
                className={syncSettings.mode === 'scheduled' ? 'primary' : ''}
                onClick={() =>
                  setSyncSettings({ ...syncSettings, mode: 'scheduled' })
                }
              >
                定时同步<span>按计划批量处理待同步数据</span>
              </button>
            </div>
            {syncSettings.mode === 'scheduled' && (
              <label>
                定时计划（Cron）
                <input
                  value={syncSettings.cron}
                  placeholder="0 * * * *"
                  onChange={(e) =>
                    setSyncSettings({ ...syncSettings, cron: e.target.value })
                  }
                />
                <small>例如 0 * * * * 表示每小时整点</small>
              </label>
            )}
            <label>
              兜底补同步间隔（分钟）
              <input
                type="number"
                min="1"
                max="1440"
                value={syncSettings.fallback_minutes}
                onChange={(e) =>
                  setSyncSettings({
                    ...syncSettings,
                    fallback_minutes: Number(e.target.value),
                  })
                }
              />
              <small>
                独立检查漏处理、失败及重启遗留记录，定时模式下也会执行。
              </small>
            </label>
            <button
              className="primary"
              disabled={busy}
              onClick={() => action(() => api('/sync/settings', syncSettings))}
            >
              保存同步设置
            </button>
          </section>
        )}
        {page === '日志' && logTab === '推送记录' && <PushRecords />}
        {page === '日志' && ['采集台账','同步台账'].includes(logTab) && <Ledger mode={logTab==='同步台账'?'sync':'crawl'} />}
        {page === '日志' && logTab === '运行日志' && (
          <section className="panel">
            <div className="toolbar">
              <h2>运行日志</h2>
              <label><input type="checkbox" checked={autoLogs} onChange={(e) => setAutoLogs(e.target.checked)} />自动刷新</label>
              <button onClick={() => loadRuntimeLogs().catch((e) => setError(e.message))}>刷新</button>
            </div>
            <p>最近 1000 条 · 每 3 秒刷新 · 服务重启后重新记录</p>
            <pre style={{ maxHeight: '65vh', overflow: 'auto' }}>{runtimeLogs || '暂无运行日志'}</pre>
          </section>
        )}
        {(page === '日志' ? logTab === '详细日志' : !!output) && (
          <section className="panel">
            <div className="toolbar">
              <h2>{page === '日志' ? '日志详情' : '操作结果 / 转换预览'}</h2>
              <button onClick={() => setOutput('')}>收起</button>
            </div>
            <pre>{output || '请在批次记录中选择一条日志。'}</pre>
          </section>
        )}

        {resolution && (
          <div className="modal" onClick={() => setResolution(null)}>
            <section className="panel" style={{maxWidth:'1000px',maxHeight:'85vh',overflow:'auto'}} onClick={(e) => e.stopPropagation()}>
              <h2>{resolution.operation === 'clear_size' ? '确认大小留空并同步' : '确认使用备用 TID 同步'}</h2>
              <p>可处理 {resolution.items.filter((item) => item.available).length} 条，共 {resolution.items.length} 条。原始数据保留，Avdb 已有文章不覆盖。</p>
              <p>{resolution.operation === 'clear_size' ? '仅处理大小超出范围的失败项，确认后目标大小为 NULL。' : '备用 TID = 原始 TID × 10000 ＋原始 TID；已占用的跳过。'}</p>
              <table><thead><tr><th>原始 TID / 标题</th><th>原始大小 / 备用 TID</th><th>检查结果</th></tr></thead><tbody>
                {resolution.items.map((item) => <tr key={item.id}><td>{item.tid} · {item.title}<p>{item.existing_website} {item.existing_title}</p></td><td>{resolution.operation === 'clear_size' ? String(item.size ?? '空') : item.target_tid}</td><td>{item.available ? '可处理' : '已占用或超出范围'}</td></tr>)}
              </tbody></table>
              <div className="toolbar"><button onClick={() => setResolution(null)}>取消</button><button disabled={busy || !resolution.items.some((item) => item.available)} onClick={() => action(async () => {const result=await api('/resolve', resolution);setResolution(null);return result})}>确认处理可用记录</button></div>
            </section>
          </div>
        )}
        {cleanOpen && (
          <div className="modal" onClick={() => setCleanOpen(false)}>
            <section
              className="panel clean-dialog"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="toolbar">
                <h2>清理指定板块</h2>
                <button onClick={() => setCleanOpen(false)}>关闭</button>
              </div>
              <p>
                多选要删除的板块。清理原始表及其转换结果，不影响目标表已展示的文章。删除历史数据可能使该板块重新采集。
              </p>
              <div className="boards">
                {Array.from(new Set(overview.groups.map((g) => g.section))).map(
                  (name) => (
                    <label key={name}>
                      <input
                        type="checkbox"
                        checked={cleanSections.includes(name)}
                        onChange={(e) => {
                          setCleanSections(
                            e.target.checked
                              ? [...cleanSections, name]
                              : cleanSections.filter((s) => s !== name),
                          )
                          setCleanup(null)
                        }}
                      />
                      {name}
                    </label>
                  ),
                )}
              </div>
              <button
                disabled={busy || !cleanSections.length}
                onClick={() =>
                  action(async () => {
                    const result = await api('/cleanup/preview', cleanFilters())
                    setCleanup(result)
                    return undefined
                  })
                }
              >
                预览删除数量
              </button>
              {cleanup && (
                <div className="warning">
                  将删除 {cleanup.count} 条文章及关联转换记录。
                  <button
                    className="danger"
                    disabled={busy || !cleanup.count}
                    onClick={() => {
                      if (
                        confirm(
                          `确认删除所选板块的 ${cleanup.count} 条原始文章及转换结果？目标表不会删除。`,
                        )
                      )
                        action(async () => {
                          const result = await api('/cleanup', {
                            filters: cleanFilters(),
                            confirmation: cleanup.confirmation,
                          })
                          setCleanup(null)
                          setCleanOpen(false)
                          return result
                        })
                    }}
                  >
                    确认删除
                  </button>
                </div>
              )}
            </section>
          </div>
        )}
        {detail && (
          <div className="modal" onClick={() => setDetail(null)}>
            <section className="panel" onClick={(e) => e.stopPropagation()}>
              <div className="toolbar">
                <h2>文章详情 #{detail.tid}</h2>
                <button onClick={() => setDetail(null)}>关闭</button>
              </div>
              <h3>{detail.title}</h3>
              <p>
                {detail.section} · {detail.website} · {detail.error}
              </p>
              <button
                onClick={() => {
                  navigator.clipboard
                    .writeText(
                      [...(detail.magnet || []), ...(detail.edk || [])].join(
                        '\n',
                      ),
                    )
                    .catch(() => setError('复制失败，请在下方手动选择'))
                }}
              >
                复制原始下载链接
              </button>
              <pre>
                {[...(detail.magnet || []), ...(detail.edk || [])].join('\n')}
              </pre>
              <div className="images">
                {detail.preview_images?.map((url, i) => (
                  <button key={i} className="detail-image-button" aria-label={`预览文章图片 ${i + 1}`} onClick={() => setDetailPreview(i)}><img
                    loading="lazy"
                    src={url}
                    alt={`文章图片 ${i + 1}`}
                    referrerPolicy="no-referrer"
                  /></button>
                ))}
              </div>
            </section>
          </div>
        )}
        {detail && detailPreview !== null && <ImagePreview items={[detail]} initialId={detail.tid} initialIndex={detailPreview} onClose={() => setDetailPreview(null)} />}
      </main>
    </div>
  )
}
createRoot(document.getElementById('root')!).render(<App />)
