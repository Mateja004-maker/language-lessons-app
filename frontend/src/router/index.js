import { createRouter, createWebHistory } from 'vue-router'
import LoginView from '@/views/LoginView.vue'
import RegisterView from '@/views/RegisterView.vue'
import LessonsView from '@/views/LessonsView.vue'
import LanguagesView from '@/views/LanguagesView.vue'
import LessonDetailView from '@/views/LessonDetailView.vue'
import ManageLessonsView from '@/views/ManageLessonsView.vue'
import ProfileView from '@/views/ProfileView.vue'
import UsersView from '@/views/UsersView.vue'
import HomeView from '@/views/HomeView.vue'
import FavoritesView from '@/views/FavoritesView.vue'
import ExamsView from '@/views/ExamsView.vue'
import ExamCreateView from '@/views/ExamCreateView.vue'
import ExamDetailsView from '@/views/ExamDetailsView.vue'
import ExamTakeView from '@/views/ExamTakeView.vue'
import ExamResultsView from '@/views/ExamResultsView.vue'
import MyResultsView from '@/views/MyResultsView.vue'
import TestAiGenerisanjeView from '@/views/TestAiGenerisanjeView.vue'


const routes = [
    { path: '/login', name: 'login', component: LoginView },

    { path: '/register', name: 'register', component: RegisterView },

    { path: '/', name: 'home', component: HomeView, meta: { requiresAuth: true } },

    { path: '/profile', name: 'profile', component: ProfileView, meta: { requiresAuth: true } },

    { path: '/admin/users', name: 'admin-users', component: UsersView, meta: { requiresAuth: true, roles: ['ADMIN'] } },

    // ✅ OVO JE FIX
    { path: '/lessons', name: 'lessons', component: LessonsView, meta: { requiresAuth: true } },

    { path: '/lessons/:id', name: 'lesson-detail', component: LessonDetailView, meta: { requiresAuth: true } },
    
    { path: '/favorites', name: 'favorites', component: FavoritesView },

    { path: '/manage/lessons', name: 'manage-lessons', component: ManageLessonsView, meta: { requiresAuth: true, roles: ['TEACHER', 'ADMIN'] } },

    { path: '/admin/languages', name: 'admin-languages', component: LanguagesView, meta: { requiresAuth: true, roles: ['ADMIN'] } },
    
    { path: '/exams', name: 'exams', component: ExamsView, meta: { requiresAuth: true, roles: ['TEACHER', 'ADMIN', 'STUDENT'] } },

    { path: '/exams/create', name: 'exam-create', component: ExamCreateView, meta: { requiresAuth: true, roles: ['TEACHER', 'ADMIN'] } },

    { path: '/exams/:id', name: 'exam-details', component: ExamDetailsView, meta: { requiresAuth: true, roles: ['TEACHER', 'ADMIN'] } },

    { path: '/exams/:id/take', name: 'exam-take', component: ExamTakeView, meta: { requiresAuth: true, roles: ['STUDENT'] } },
    
    { path: '/exams/:id/results', name: 'exam-results', component: ExamResultsView, meta: { requiresAuth: true, roles: ['TEACHER', 'ADMIN'] } },

    { path: '/my-results', name: 'my-results', component: MyResultsView, meta: { requiresAuth: true, roles: ['STUDENT'] } },

    // Privremeni test-ekran za AI generisanje pitanja - samo rucno otvaranje, ne ide u navbar
    { path: '/test-ai-generisanje', name: 'test-ai-generisanje', component: TestAiGenerisanjeView, meta: { requiresAuth: true, roles: ['TEACHER', 'ADMIN'] } }

]

const router = createRouter({
    history: createWebHistory(),
    routes
})

router.beforeEach((to) => {
    const token = localStorage.getItem('access_token')
    const role = localStorage.getItem('user_role')
    if (to.name === 'register') return true

    // Ako je već ulogovan, nema smisla da stoji na /login
    if ((to.name === 'login' || to.name === 'register') && token) {
        return { name: 'lessons' }
    }

    if (to.meta.requiresAuth && !token) return { name: 'login' }

    if (to.meta.roles && (!role || !to.meta.roles.includes(role))) {
        return { name: 'lessons' }
    }

    return true
})

export default router