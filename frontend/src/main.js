import 'bootstrap/dist/css/bootstrap.min.css'
import 'bootstrap/dist/js/bootstrap.bundle.min.js'
import './assets/main.css'
import 'bootstrap-icons/font/bootstrap-icons.css'

import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

import '@fortawesome/fontawesome-free/css/all.min.css'

createApp(App).use(router).mount('#app')