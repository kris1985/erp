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
import { canPermission, permissionDirective } from './directives/permission'
import { pinImageViewerClose } from './utils/imageViewerClose'

pinImageViewerClose()

const app = createApp(App)
app.config.globalProperties.$can = canPermission
app
  .use(createPinia())
  .use(router)
  .use(ElementPlus, { locale: zhCn })
  .directive('permission', permissionDirective)
  .mount('#app')
