import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import 'vant/lib/index.css'
import './styles.css'
import './admin.css'

createApp(App).use(createPinia()).use(router).use(ElementPlus, { locale: zhCn }).mount('#app')
