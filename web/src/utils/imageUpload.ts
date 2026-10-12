/** 上传前将超大图片压缩到上限以内（默认 5MB）。 */

const DEFAULT_MAX_BYTES = 5 * 1024 * 1024
const START_MAX_EDGE = 2560
const MIN_EDGE = 480

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      resolve(img)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('图片读取失败'))
    }
    img.src = url
  })
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  type: string,
  quality: number,
): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, type, quality))
}

/**
 * 若图片未超限则原样返回；否则用 canvas 压成 JPEG，逐步降画质/边长直到 ≤ maxBytes。
 */
export async function prepareImageForUpload(
  file: File,
  maxBytes = DEFAULT_MAX_BYTES,
): Promise<File> {
  if (!file.type.startsWith('image/') || file.size <= maxBytes) return file

  const img = await loadImage(file)
  let maxEdge = Math.min(Math.max(img.width, img.height), START_MAX_EDGE)
  let quality = 0.88
  const outType = 'image/jpeg'
  const baseName = (file.name || 'image').replace(/\.[^.]+$/, '') || 'image'
  let best: Blob | null = null

  for (let attempt = 0; attempt < 14; attempt++) {
    const scale = Math.min(1, maxEdge / Math.max(img.width, img.height, 1))
    const w = Math.max(1, Math.round(img.width * scale))
    const h = Math.max(1, Math.round(img.height * scale))
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('图片处理失败')
    ctx.fillStyle = '#fff'
    ctx.fillRect(0, 0, w, h)
    ctx.drawImage(img, 0, 0, w, h)

    const blob = await canvasToBlob(canvas, outType, quality)
    if (!blob) throw new Error('图片压缩失败')
    if (!best || blob.size < best.size) best = blob
    if (blob.size <= maxBytes) {
      return new File([blob], `${baseName}.jpg`, { type: outType, lastModified: Date.now() })
    }

    if (quality > 0.55) {
      quality = Math.max(0.5, quality - 0.12)
    } else {
      maxEdge = Math.round(maxEdge * 0.72)
      quality = 0.82
      if (maxEdge < MIN_EDGE) break
    }
  }

  if (best && best.size <= maxBytes) {
    return new File([best], `${baseName}.jpg`, { type: outType, lastModified: Date.now() })
  }
  throw new Error('图片过大，压缩后仍无法上传')
}
