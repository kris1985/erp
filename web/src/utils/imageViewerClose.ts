/** 把 Element Plus 图片预览的关闭按钮贴在当前图片右上角。 */
export function pinImageViewerClose() {
  let raf = 0

  const place = () => {
    const viewers = document.querySelectorAll<HTMLElement>('.el-image-viewer__wrapper')
    if (!viewers.length) {
      raf = 0
      return
    }
    viewers.forEach((viewer) => {
      const img = viewer.querySelector<HTMLElement>('.el-image-viewer__img')
      const close = viewer.querySelector<HTMLElement>('.el-image-viewer__close')
      if (!img || !close) return
      const rect = img.getBoundingClientRect()
      if (rect.width < 8 || rect.height < 8) return
      const size = close.offsetWidth || 44
      const gap = 8
      const visibleTop = Math.max(rect.top, 0)
      const visibleRight = Math.min(rect.right, window.innerWidth)
      const top = Math.max(8, visibleTop + gap)
      const left = Math.max(8, visibleRight - size - gap)
      close.style.top = `${top}px`
      close.style.right = 'auto'
      close.style.left = `${left}px`
    })
    raf = requestAnimationFrame(place)
  }

  const start = () => {
    if (!raf && document.querySelector('.el-image-viewer__wrapper')) {
      raf = requestAnimationFrame(place)
    }
  }

  const observer = new MutationObserver((records) => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (!(node instanceof HTMLElement)) continue
        if (
          node.classList.contains('el-image-viewer__wrapper') ||
          node.querySelector('.el-image-viewer__wrapper')
        ) {
          start()
          return
        }
      }
    }
  })
  observer.observe(document.body, { childList: true, subtree: true })
  start()
}
