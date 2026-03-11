import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '@/views/LoginView.vue'
import LessonsView from '@/views/LessonsView.vue'
import LanguagesView from '@/views/LanguagesView.vue'
import LessonDetailView from '@/views/LessonDetailView.vue'
import ManageLessonsView from '@/views/ManageLessonsView.vue'


const routes = [
    { path: '/login', name: 'login', component: LoginView },

    { path: '/', name: 'lessons', component: LessonsView, meta: { requiresAuth: true } },

    { path: '/lessons/:id', name: 'lesson-detail', component: LessonDetailView, meta: { requiresAuth: true } },

    { path: '/manage/lessons', name: 'manage-lessons', component: ManageLessonsView, meta: { requiresAuth: true, roles: ['TEACHER', 'ADMIN'] } },


    // Admin stranica (samo ADMIN)
    { path: '/admin/languages', name: 'admin-languages', component: LanguagesView, meta: { requiresAuth: true, roles: ['ADMIN'] } }
]

const router = createRouter({
    history: createWebHistory(),
    routes
})

router.beforeEach((to) => {
    const token = localStorage.getItem('access_token')
    const role = localStorage.getItem('user_role')

    // Ako je već ulogovan, nema smisla da stoji na /login
    if (to.name === 'login' && token) return { name: 'lessons' }

    if (to.meta.requiresAuth && !token) return { name: 'login' }

    if (to.meta.roles && (!role || !to.meta.roles.includes(role))) {
        return { name: 'lessons' }
    }

    return true
})

export default router