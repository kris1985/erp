import { createSSRApp } from 'vue'
import App from './App.vue'
import './styles.scss'
import { installPageTitle } from './services/page-title'

installPageTitle()

export function createApp() {
  const app = createSSRApp(App)
  return { app }
}
