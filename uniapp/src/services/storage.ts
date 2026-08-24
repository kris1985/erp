const KEYS = {
  token: 'ws_token',
  profile: 'ws_profile',
  credentials: 'ws_saved_credentials',
} as const

export interface UserProfile {
  id: number
  displayName: string
  tenantName: string
  role: string
  isLeader: boolean
  mustChangePassword: boolean
}

export interface SavedCredentials {
  identifier: string
  password: string
}

export function getToken(): string {
  return String(uni.getStorageSync(KEYS.token) || '')
}

export function setSession(token: string, profile: UserProfile) {
  uni.setStorageSync(KEYS.token, token)
  uni.setStorageSync(KEYS.profile, profile)
}

export function getProfile(): UserProfile | null {
  return (uni.getStorageSync(KEYS.profile) as UserProfile) || null
}

export function clearSession() {
  uni.removeStorageSync(KEYS.token)
  uni.removeStorageSync(KEYS.profile)
}

export function getSavedCredentials(): SavedCredentials | null {
  return (uni.getStorageSync(KEYS.credentials) as SavedCredentials) || null
}

export function saveCredentials(identifier: string, password: string) {
  uni.setStorageSync(KEYS.credentials, { identifier, password })
}

export function clearSavedCredentials() {
  uni.removeStorageSync(KEYS.credentials)
}
