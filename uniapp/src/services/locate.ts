export type GeoPoint = { latitude: number; longitude: number }

// #ifdef H5
function locationErrorMessage(error: { code?: number; message?: string }): string {
  const raw = String(error?.message || '')
  if (/secure|https/i.test(raw)) return '当前是 http 访问，浏览器禁止定位，请用 https 打开'
  if (Number(error?.code) === 1) return '定位被拒绝，请在浏览器设置里允许使用位置'
  if (Number(error?.code) === 3) return '定位超时，请打开手机定位后再试'
  return '定位失败，请打开系统定位并允许浏览器使用位置'
}

function browserLocation(highAccuracy: boolean, timeout: number): Promise<GeoPoint> {
  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({
        latitude: pos.coords.latitude,
        longitude: pos.coords.longitude,
      }),
      (err) => reject(err),
      {
        enableHighAccuracy: highAccuracy,
        timeout,
        maximumAge: 5000,
      },
    )
  })
}
// #endif

/** 取当前位置。H5 先用网络定位，电脑浏览器没有 GPS 时高精度会直接失败。 */
export function currentLocation(): Promise<GeoPoint> {
  // #ifdef H5
  if (typeof window !== 'undefined' && window.isSecureContext === false) {
    return Promise.reject(new Error('当前是 http 访问，浏览器禁止定位，请用 https 打开'))
  }
  if (typeof navigator === 'undefined' || !navigator.geolocation) {
    return Promise.reject(new Error('当前浏览器不支持定位'))
  }
  return browserLocation(false, 12000).catch((error) => {
    if (Number(error?.code) === 1) return Promise.reject(new Error(locationErrorMessage(error)))
    return browserLocation(true, 10000).catch((again) => Promise.reject(new Error(locationErrorMessage(again))))
  })
  // #endif

  // #ifndef H5
  return new Promise((resolve, reject) => {
    uni.getLocation({
      type: 'wgs84',
      isHighAccuracy: true,
      success: (res) => resolve({
        latitude: Number(res.latitude),
        longitude: Number(res.longitude),
      }),
      fail: () => reject(new Error('定位失败，请允许使用位置')),
    })
  })
  // #endif
}
