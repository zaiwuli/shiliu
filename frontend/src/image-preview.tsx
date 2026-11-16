import { useEffect, useRef, useState } from 'react'
import type { TouchEvent } from 'react'
import './image-preview.css'

type Item = { tid: number; title: string; preview_images: string[] }
export function ImagePreview({ items, initialId, initialIndex = 0, onClose }: { items: Item[]; initialId: number; initialIndex?: number; onClose: () => void }) {
  const [articleId, setArticleId] = useState(initialId)
  const [index, setIndex] = useState(initialIndex)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [failed, setFailed] = useState(false)
  const closeRef = useRef(onClose)
  const dialogRef = useRef<HTMLDivElement>(null)
  const thumbRef = useRef<HTMLDivElement>(null)
  const gesture = useRef({ x: 0, y: 0, distance: 0, zoom: 1, panX: 0, panY: 0, multi: false })
  const lastTap = useRef(0)
  const position = items.findIndex(a => a.tid === articleId)
  const article = items[position]
  const images = article?.preview_images || []
  closeRef.current = onClose
  const select = (next: number) => { setIndex(next); setZoom(1); setPan({ x: 0, y: 0 }); setFailed(false) }
  const move = (direction: number) => select((index + direction + images.length) % images.length)
  const switchArticle = (direction: number) => {
    for (let p = position + direction; p >= 0 && p < items.length; p += direction) {
      if (items[p].preview_images.length) { setArticleId(items[p].tid); select(0); return }
    }
  }
  const hasArticle = (direction: number) => direction < 0
    ? items.slice(0, position).some(a => a.preview_images.length)
    : items.slice(position + 1).some(a => a.preview_images.length)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialogRef.current?.focus()
    const marker = { ...window.history.state, shiliuPreview: true }
    window.history.pushState(marker, '')
    let popped = false
    const pop = () => { popped = true; closeRef.current() }
    window.addEventListener('popstate', pop)
    return () => {
      window.removeEventListener('popstate', pop)
      if (!popped && window.history.state?.shiliuPreview) window.history.back()
      document.body.style.overflow = overflow
      previous?.focus()
    }
  }, [])
  useEffect(() => { thumbRef.current?.querySelector('[aria-pressed="true"]')?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' }) }, [index, articleId])
  const distance = (e: TouchEvent) => Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY)
  const touchStart = (e: TouchEvent) => {
    gesture.current = { x: e.touches[0].clientX, y: e.touches[0].clientY, distance: e.touches.length > 1 ? distance(e) : 0, zoom, panX: pan.x, panY: pan.y, multi: e.touches.length > 1 }
  }
  const touchMove = (e: TouchEvent) => {
    const g = gesture.current
    if (e.touches.length > 1 && g.distance) {
      setZoom(Math.min(4, Math.max(1, g.zoom * distance(e) / g.distance)))
    } else if (zoom > 1 && !g.multi) {
      const limit = Math.max(window.innerWidth, window.innerHeight) * (zoom - 1) / 2
      setPan({ x: Math.max(-limit, Math.min(limit, g.panX + e.touches[0].clientX - g.x)), y: Math.max(-limit, Math.min(limit, g.panY + e.touches[0].clientY - g.y)) })
    }
  }
  const touchEnd = (e: TouchEvent) => {
    const g = gesture.current
    if (g.multi) { if (zoom <= 1) setPan({ x: 0, y: 0 }); return }
    const dx = e.changedTouches[0].clientX - g.x, dy = e.changedTouches[0].clientY - g.y
    if (zoom === 1 && Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy)) { move(dx < 0 ? 1 : -1); return }
    if (Math.abs(dx) < 10 && Math.abs(dy) < 10) {
      const now = Date.now()
      if (now - lastTap.current < 300) { setZoom(zoom > 1 ? 1 : 2); setPan({ x: 0, y: 0 }) }
      lastTap.current = now
    }
  }
  return <div className="resource-preview" ref={dialogRef} tabIndex={-1} role="dialog" aria-modal="true" aria-label="图片预览" onKeyDown={e => {
    if (e.key === 'Escape') { e.stopPropagation(); onClose() }
    if (e.key === 'ArrowLeft') move(-1)
    if (e.key === 'ArrowRight') move(1)
    if (e.key === 'Tab') {
      const buttons = dialogRef.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')
      if (!buttons?.length) return
      const first = buttons[0], last = buttons[buttons.length - 1]
      if (e.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
  }}>
    <div className="resource-preview-header"><button onClick={onClose} aria-label="关闭预览">返回</button><span aria-live="polite">{index + 1} / {images.length}</span><button onClick={() => { setZoom(zoom > 1 ? 1 : 2); setPan({ x: 0, y: 0 }) }}>{zoom > 1 ? '还原' : '放大'}</button></div>
    <p className="resource-preview-title">{article?.title}</p>
    <div className="resource-preview-stage" onTouchStart={touchStart} onTouchMove={touchMove} onTouchEnd={touchEnd} onTouchCancel={() => { gesture.current.multi = true }}>
      {failed ? <div className="resource-preview-error"><p>图片加载失败</p><button onClick={() => setFailed(false)}>重新加载</button></div> : <img key={`${articleId}-${index}`} src={images[index]} alt={`${article?.title}，图片 ${index + 1}`} referrerPolicy="no-referrer" draggable={false} style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }} onError={() => setFailed(true)} />}
      {images.length > 1 && <><button className="resource-preview-prev" aria-label="上一张" onClick={() => move(-1)}>‹</button><button className="resource-preview-next" aria-label="下一张" onClick={() => move(1)}>›</button></>}
    </div>
    <div className="resource-preview-footer"><div className="resource-preview-articles"><button disabled={!hasArticle(-1)} onClick={() => switchArticle(-1)}>上一篇</button><span>{zoom > 1 ? '拖动查看 · 双击还原' : '左右滑动切图 · 双指缩放'}</span><button disabled={!hasArticle(1)} onClick={() => switchArticle(1)}>下一篇</button></div>
      {images.length > 1 && <div ref={thumbRef} className="resource-preview-thumbs">{images.map((src, i) => <button key={i} aria-label={`查看第 ${i + 1} 张`} aria-pressed={i === index} onClick={() => select(i)}><img loading="lazy" src={src} alt="" referrerPolicy="no-referrer" /></button>)}</div>}
    </div>
  </div>
}
