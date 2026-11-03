/**
 * 正式包启动时按系统检查更新。
 * Android 整包下载 APK；iOS 整包只能打开 TestFlight / App Store / 企业分发链接。
 * 热更新下载 wgt，只替换页面资源，装完重启。壳版本低于运营端要求时，先走整包。
 * 标准基座的版本号不是业务包版本，跳过检查。
 */

type RemoteRelease = {
  version_name: string
  version_code: number
  download_url: string
  notes: string
  force_update: boolean
  min_native_version_code?: number | null
}

type RemoteChannels = {
  native: RemoteRelease | null
  wgt: RemoteRelease | null
}

type PlatformName = 'android' | 'ios'

let checking = false
let dialogOpen = false
let skippedCode = 0

function apiBase(): string {
  let base = String(import.meta.env.VITE_API_BASE_URL || '/api/v1')
  // H5 走同源；这段在 App 打包时会被编译掉。
  // #ifdef H5
  base = '/api/v1'
  // #endif
  return base.replace(/\/$/, '')
}

function platformName(): PlatformName {
  return plus.os.name === 'iOS' ? 'ios' : 'android'
}

function nativeVersionCode(): number {
  const code = Number(plus.runtime.versionCode || 0)
  return Number.isFinite(code) ? code : 0
}

function widgetVersionCode(): Promise<number> {
  return new Promise((resolve) => {
    const fallback = nativeVersionCode()
    plus.runtime.getProperty(
      plus.runtime.appid,
      (info) => {
        const code = Number(info.versionCode || 0)
        resolve(Number.isFinite(code) && code > 0 ? code : fallback)
      },
      () => resolve(fallback),
    )
  })
}

function asRelease(raw: RemoteRelease | null | undefined): RemoteRelease | null {
  if (!raw?.download_url || !Number.isFinite(Number(raw.version_code))) return null
  return {
    version_name: String(raw.version_name || ''),
    version_code: Number(raw.version_code),
    download_url: String(raw.download_url),
    notes: String(raw.notes || ''),
    force_update: Boolean(raw.force_update),
    min_native_version_code: raw.min_native_version_code ? Number(raw.min_native_version_code) : null,
  }
}

async function fetchChannels(platform: PlatformName): Promise<RemoteChannels> {
  const response = await uni.request({
    url: `${apiBase()}/app-releases/current?platform=${platform}`,
    method: 'GET',
    timeout: 8000,
  })
  if (response.statusCode < 200 || response.statusCode >= 300) return { native: null, wgt: null }
  let payload: unknown = response.data
  if (typeof payload === 'string') {
    try {
      payload = JSON.parse(payload)
    } catch {
      return { native: null, wgt: null }
    }
  }
  const body = payload as { ok?: boolean; data?: { native?: RemoteRelease | null; wgt?: RemoteRelease | null } }
  if (!body || body.ok === false || !body.data) return { native: null, wgt: null }
  return {
    native: asRelease(body.data.native),
    wgt: asRelease(body.data.wgt),
  }
}

function removeLocal(path: string): Promise<void> {
  return new Promise((resolve) => {
    plus.io.resolveLocalFileSystemURL(
      path,
      (entry) => entry.remove(() => resolve(), () => resolve()),
      () => resolve(),
    )
  })
}

function downloadFile(url: string, filename: string): Promise<string | null> {
  return removeLocal(filename).then(
    () =>
      new Promise((resolve) => {
        const waiting = plus.nativeUI.showWaiting('正在下载 0%')
        const task = plus.downloader.createDownload(url, { filename }, (download, status) => {
          waiting.close()
          if (status !== 200 || !download.filename) {
            uni.showToast({ title: '下载失败', icon: 'none' })
            resolve(null)
            return
          }
          resolve(download.filename)
        })
        task.addEventListener('statechanged', (item) => {
          const total = Number(item.totalSize || 0)
          const loaded = Number(item.downloadedSize || 0)
          if (total > 0) waiting.setTitle(`正在下载 ${Math.min(100, Math.floor((loaded / total) * 100))}%`)
        })
        task.start()
      }),
  )
}

function installApk(path: string) {
  plus.runtime.install(
    path,
    { force: false },
    () => {
      uni.showToast({ title: '请按系统提示完成安装', icon: 'none' })
    },
    () => {
      uni.showToast({ title: '无法打开安装程序', icon: 'none' })
    },
  )
}

function installWgt(path: string) {
  plus.runtime.install(
    path,
    { force: false },
    () => {
      plus.runtime.restart()
    },
    () => {
      uni.showToast({ title: '热更新安装失败', icon: 'none' })
    },
  )
}

function startDownload(release: RemoteRelease, action: 'apk' | 'wgt' | 'link') {
  if (action === 'link') {
    plus.runtime.openURL(release.download_url)
    return
  }
  const ext = action === 'wgt' ? 'wgt' : 'apk'
  const filename = `_doc/tyulan-${release.version_code}.${ext}`
  void downloadFile(release.download_url, filename).then((path) => {
    if (!path) return
    if (action === 'wgt') installWgt(path)
    else installApk(path)
  })
}

function askUpdate(release: RemoteRelease, action: 'apk' | 'wgt' | 'link') {
  if (dialogOpen) return
  if (!release.force_update && skippedCode === release.version_code) return
  const notes = (release.notes || (action === 'wgt' ? '有资源更新，安装后会重新打开' : '请更新后继续使用')).slice(0, 300)
  const title = `发现新版本 ${release.version_name}`
  const confirmText = action === 'link' ? '前往更新' : '立即更新'
  dialogOpen = true
  const finish = (confirmed: boolean) => {
    dialogOpen = false
    if (confirmed) {
      startDownload(release, action)
      return
    }
    if (release.force_update) {
      setTimeout(() => askUpdate(release, action), 300)
      return
    }
    skippedCode = release.version_code
  }
  // 页面级 showModal 在 App 启动跳转时不会出现。系统对话框不依赖当前页面。
  if (release.force_update) {
    plus.nativeUI.alert(notes, () => finish(true), title, confirmText)
    return
  }
  plus.nativeUI.confirm(notes, (event) => finish(event.index === 0), title, [confirmText, '稍后'])
}

async function checkPlatformUpdate() {
  if (checking || dialogOpen) return
  if (plus.runtime.appid === 'HBuilder') return
  checking = true
  try {
    await compareChannels()
  } finally {
    checking = false
  }
}

async function compareChannels() {
  const platform = platformName()
  const channels = await fetchChannels(platform)
  const shell = nativeVersionCode()
  const native = channels.native
  if (native && native.version_code > shell) {
    askUpdate(native, platform === 'ios' ? 'link' : 'apk')
    return
  }
  const wgt = channels.wgt
  if (!wgt) return
  const resource = await widgetVersionCode()
  const minShell = Number(wgt.min_native_version_code || 0)
  if (minShell && shell < minShell) return
  if (wgt.version_code > resource) askUpdate(wgt, 'wgt')
}

export async function checkAppUpdate(): Promise<void> {
  // #ifdef APP-PLUS
  try {
    await checkPlatformUpdate()
  } catch (error) {
    console.info('[app-update] skip', error)
  }
  // #endif
}
