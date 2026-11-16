import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import './push-toast.css'
type Notice={id:number;message:string;kind:'pending'|'success'|'error';recordId?:number}
export function notifyPush(message:string,recordId?:number){window.dispatchEvent(new CustomEvent('shiliu:push-toast',{detail:{message,recordId}}))}
export function PushToasts(){
 const [notices,setNotices]=useState<Notice[]>([])
 useEffect(()=>{
  let serial=0,disposed=false
  const timers=new Set<ReturnType<typeof setTimeout>>()
  const controllers=new Set<AbortController>()
  const later=(fn:()=>void,ms:number)=>{const timer=setTimeout(()=>{timers.delete(timer);if(!disposed)fn()},ms);timers.add(timer)}
  const show=(notice:Notice)=>{setNotices(old=>[...old.filter(n=>n.id!==notice.id),notice].slice(-3));later(()=>setNotices(old=>old.filter(n=>n.id!==notice.id)),notice.kind==='error'?9000:5000)}
  const receive=(event:Event)=>{
   const {message,recordId}=(event as CustomEvent<{message:string;recordId?:number}>).detail
   const id=++serial
   show({id,message,recordId,kind:recordId?'pending':'error'})
   if(!recordId)return
   const started=Date.now()
   const poll=async()=>{
    const controller=new AbortController();controllers.add(controller)
    const timeout=setTimeout(()=>controller.abort(),10000)
    try{
     const r=await fetch(`/api/avdb/push-records/${recordId}`,{signal:controller.signal})
     if(r.ok){const data=await r.json();if(disposed)return
      if(!['pending','sending'].includes(data.status)){show({id:++serial,recordId,kind:data.status==='submitted'?'success':'error',message:data.status==='submitted'?'已提交至 AVDB':data.message||'推送未完成，请查看记录'});return}
     }
    }catch{/* A disconnected browser must not resubmit the download. */}
    finally{clearTimeout(timeout);controllers.delete(controller)}
    if(Date.now()-started<10*60*1000)later(()=>void poll(),3000)
   }
   later(()=>void poll(),1500)
  }
  window.addEventListener('shiliu:push-toast',receive)
  return()=>{disposed=true;timers.forEach(clearTimeout);controllers.forEach(c=>c.abort());window.removeEventListener('shiliu:push-toast',receive)}
 },[])
 return createPortal(<div className="push-toasts" aria-live="polite" aria-relevant="additions">{notices.map(n=><div key={n.id} className={`push-toast ${n.kind}`} role={n.kind==='error'?'alert':'status'}><span className="push-toast-icon" aria-hidden="true">{n.kind==='success'?'✓':n.kind==='error'?'!':''}</span><div className="push-toast-body"><strong>{n.message}</strong>{n.recordId&&<button onClick={()=>{window.dispatchEvent(new Event('shiliu:open-push-records'));setNotices(old=>old.filter(v=>v.id!==n.id))}}>查看记录 ↗</button>}</div><button className="push-toast-close" aria-label="关闭提示" onClick={()=>setNotices(old=>old.filter(v=>v.id!==n.id))}>×</button></div>)}</div>,document.body)
}
