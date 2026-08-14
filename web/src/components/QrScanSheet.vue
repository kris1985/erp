<template>
  <van-popup
    v-model:show="visible"
    position="bottom"
    :style="{ height: '88%' }"
    round
    closeable
    @closed="onClosed"
  >
    <div class="qr-scan">
      <div class="qr-scan__title">扫码计件</div>
      <p class="qr-scan__hint">对准工位二维码或捆标二维码</p>
      <div id="h5-qr-reader" class="qr-scan__reader" />
      <p v-if="error" class="qr-scan__error">{{ error }}</p>
      <van-button v-if="error" round block type="primary" class="qr-scan__retry" @click="start">
        重试
      </van-button>
    </div>
  </van-popup>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { Html5Qrcode } from 'html5-qrcode'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

const router = useRouter()
const visible = ref(false)
const error = ref('')
let scanner: Html5Qrcode | null = null
let handling = false

watch(
  () => props.show,
  async (v) => {
    visible.value = v
    if (v) {
      error.value = ''
      handling = false
      await nextTick()
      await start()
    } else {
      await stop()
    }
  },
)

watch(visible, (v) => {
  if (!v) emit('update:show', false)
})

function parseScanText(raw: string): string | null {
  const text = (raw || '').trim()
  if (!text) return null

  // Absolute or relative URL containing /scan/ or /trace/
  try {
    const url = text.includes('://') ? new URL(text) : new URL(text, window.location.origin)
    const path = url.pathname
    const scan = path.match(/\/scan\/([^/]+)/i)
    if (scan?.[1]) return `/scan/${decodeURIComponent(scan[1])}`
    const trace = path.match(/\/trace(?:-print|-report)?\/([^/]+)/i)
    if (trace?.[1]) return `/trace/${decodeURIComponent(trace[1])}`
  } catch {
    // not a URL
  }

  const pathMatch = text.match(/(?:^|\/)(scan|trace)\/([A-Za-z0-9_-]+)/i)
  if (pathMatch) {
    return `/${pathMatch[1].toLowerCase()}/${pathMatch[2]}`
  }

  // Bare station / trace code
  if (/^[A-Za-z0-9][A-Za-z0-9_-]{1,39}$/.test(text)) {
    return `/scan/${text.toUpperCase()}`
  }

  return null
}

async function onScanSuccess(decoded: string) {
  if (handling) return
  const target = parseScanText(decoded)
  if (!target) {
    showToast('无法识别该二维码')
    return
  }
  handling = true
  await stop()
  visible.value = false
  emit('update:show', false)
  showToast(target.startsWith('/trace') ? '已识别捆标' : '已识别工位')
  router.push(target)
}

async function start() {
  error.value = ''
  await stop()
  try {
    scanner = new Html5Qrcode('h5-qr-reader')
    await scanner.start(
      { facingMode: 'environment' },
      {
        fps: 10,
        qrbox: (viewW, viewH) => {
          const edge = Math.floor(Math.min(viewW, viewH) * 0.72)
          return { width: edge, height: edge }
        },
        aspectRatio: 1,
      },
      (decoded) => {
        void onScanSuccess(decoded)
      },
      () => {
        // ignore frame miss
      },
    )
  } catch (e: any) {
    error.value = e?.message?.includes('Permission')
      ? '请允许使用相机后重试'
      : e?.message || '无法打开相机，请检查权限或使用 HTTPS'
    scanner = null
  }
}

async function stop() {
  if (!scanner) return
  try {
    if (scanner.isScanning) {
      await scanner.stop()
    }
    scanner.clear()
  } catch {
    // ignore
  }
  scanner = null
}

async function onClosed() {
  await stop()
  emit('update:show', false)
}
</script>

<style scoped>
.qr-scan {
  padding: 16px 16px 28px;
  height: 100%;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
}

.qr-scan__title {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
  text-align: center;
  margin-bottom: 4px;
}

.qr-scan__hint {
  margin: 0 0 14px;
  text-align: center;
  font-size: 13px;
  color: var(--ws-muted);
}

.qr-scan__reader {
  flex: 1;
  min-height: 280px;
  border-radius: 16px;
  overflow: hidden;
  background: #111;
}

.qr-scan__reader :deep(video) {
  border-radius: 16px;
}

.qr-scan__error {
  margin: 16px 0 0;
  text-align: center;
  color: var(--ws-danger);
  font-size: 14px;
}

.qr-scan__retry {
  margin-top: 12px;
}
</style>
