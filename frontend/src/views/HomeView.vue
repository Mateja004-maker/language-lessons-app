<script setup>
import { onMounted, ref, computed } from 'vue'
import { api } from '@/services/api'
import { Pie } from 'vue-chartjs'
import {
  Chart as ChartJS,
  Title,
  Tooltip,
  Legend,
  ArcElement
} from 'chart.js'

ChartJS.register(Title, Tooltip, Legend, ArcElement)

const profile = ref(null)
const lessons = ref([])
const languages = ref([])
const subjects = ref([])
const users = ref([])
const favorites = ref([])
const progress = ref([])
const loading = ref(false)

const selected_language_ids = ref([])
const languageChoiceError = ref('')
const savingLanguage = ref(false)

const needsLanguageChoice = computed(() =>
  profile.value &&
  role !== 'ADMIN' &&
  !(profile.value.subjects && profile.value.subjects.length)
)

const languageQuestion = computed(() => {
  if (role === 'TEACHER') return 'Koje predmete želiš da predaješ?'
  return 'Koje predmete želiš da učiš?'
})

async function saveLanguageChoice() {
  languageChoiceError.value = ''

  if (!selected_language_ids.value.length) {
    languageChoiceError.value = 'Moraš da izabereš bar jedan predmet.'
    return
  }

  savingLanguage.value = true

  try {
    await api.put('/profile', {
      display_name: profile.value?.display_name || '',
      learning_language_id: selected_language_ids.value[0],
      subject_ids: selected_language_ids.value
    })

    await loadData()
  } catch (e) {
    languageChoiceError.value =
      e?.response?.data?.error || 'Greška pri čuvanju predmeta.'
  } finally {
    savingLanguage.value = false
  }
}

const role = localStorage.getItem('user_role')

const pendingUsers = computed(() =>
  users.value.filter(
    u => u.is_active !== 1 && u.role !== 'ADMIN'
  )
)

const subjectNames = computed(() => {
  if (!profile.value?.subjects || !subjects.value.length) return ''
  return profile.value.subjects
    .map(id => subjects.value.find(s => s.id === id)?.name)
    .filter(Boolean)
    .join(', ')
})

async function loadData() {
  loading.value = true

  try {
    const requests = [
      api.get('/profile'),
      api.get('/lessons'),
      api.get('/languages'),
      api.get('/subjects')
    ]

    if (role === 'STUDENT') {
      requests.push(api.get('/favorites'))
      requests.push(api.get('/progress'))
    }

    const responses = await Promise.all(requests)

    const profileData = responses[0].data
    const lessonsData = responses[1].data
    const languagesData = responses[2].data
    const subjectsData = responses[3].data

    profile.value = profileData
    lessons.value = lessonsData
    languages.value = languagesData
    subjects.value = subjectsData

    if (role === 'STUDENT') {
      favorites.value = responses[4].data
      progress.value = responses[5].data
    }

    if (role === 'ADMIN') {
      const { data: usersData } = await api.get('/users')
      users.value = usersData
    }


  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}
const heroText = computed(() => {
  if (role === 'ADMIN') {
    return 'Manage users, approve registrations and organize languages from one dashboard.'
  }

  if (role === 'TEACHER') {
    return 'Create, organize and manage lessons for the language you teach.'
  }

  return 'Continue learning, open your lessons and follow content for your selected language.'
})

const progressPercent = computed(() => {
  if (!lessons.value.length) return 0
  return Math.round((progress.value.length / lessons.value.length) * 100)
})

const filteredLessons = computed(() => {
  // Backend (/api/lessons) vec vraca lekcije filtrirane po SVIM predmetima
  // korisnika (student_subjects/teacher_subjects), dodatni filter ovde nije potreban.
  return lessons.value
})

const lessonsByLevel = computed(() => {
  const levels = {
    A1: 0,
    A2: 0,
    B1: 0,
    B2: 0,
    C1: 0,
    C2: 0
  }

  filteredLessons.value.forEach(lesson => {
    const level = lesson.level?.toUpperCase()
    if (levels[level] !== undefined) {
      levels[level]++
    }
  })

  return levels
})

const levelChartData = computed(() => ({
  labels: Object.keys(lessonsByLevel.value),
  datasets: [
    {
      data: Object.values(lessonsByLevel.value),
      backgroundColor: [
        '#2563eb',
        '#10b981',
        '#f59e0b',
        '#ef4444',
        '#8b5cf6',
        '#14b8a6'
      ]
    }
  ]
}))

const levelChartOptions = {
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: {
      position: 'bottom'
    }
  }
}

onMounted(loadData)

// AI kartice (ADMIN i TEACHER): samo brojevi iz postojećih GET ruta, bez modela.
// Učitavaju se odvojeno; ako ruta vrati grešku (npr. 409 bez migracije), kartica se ne prikazuje.
const aiPendingCount = ref(null)
const mySecondRatingCount = ref(null)

async function loadAiCounts() {
  if (role !== 'ADMIN' && role !== 'TEACHER') return
  const [pending, secondRating] = await Promise.allSettled([
    api.get('/ai/artifacts', { params: { status: 'predlog' } }),
    api.get('/ai/artifacts/second-rating')
  ])
  aiPendingCount.value =
    pending.status === 'fulfilled' && Array.isArray(pending.value.data) ? pending.value.data.length : null
  mySecondRatingCount.value =
    secondRating.status === 'fulfilled' && Array.isArray(secondRating.value.data) ? secondRating.value.data.length : null
}

const aiCards = computed(() => [
  aiPendingCount.value !== null && {
    key: 'pending', to: '/ai/predlozi', cls: 'stat-orange', icon: 'fa-solid fa-wand-magic-sparkles',
    title: 'AI predlozi na čekanju', value: aiPendingCount.value, text: 'Predlozi pitanja koji čekaju odluku'
  },
  mySecondRatingCount.value !== null && {
    key: 'second', to: '/ai/druga-ocena', cls: 'stat-purple', icon: 'fa-solid fa-scale-balanced',
    title: 'Moja druga ocena', value: mySecondRatingCount.value, text: 'Predlozi koji čekaju tvoju drugu ocenu'
  }
].filter(Boolean))

onMounted(loadAiCounts)
</script>

<template>
  <div class="container py-4">

    <!-- HERO -->
    <div class="hero-box mb-4">
      <div class="row align-items-center g-4">
        <div class="col-12 col-lg-8">
          <!-- ADMIN: uloga se već vidi u navbaru, ne ponavlja se -->
          <div v-if="role !== 'ADMIN'" class="hero-badge mb-3">
            {{ role }}
          </div>

          <h1 class="hero-title mb-2">
            Welcome back, {{ profile?.display_name || 'User' }}
          </h1>
          <div
            v-if="subjectNames && role !== 'ADMIN'"
            class="hero-language mb-3"
          >
            {{
              role === 'TEACHER'
                ? `Teaching: ${subjectNames}`
                : `Learning: ${subjectNames}`
            }}
          </div>

          <p class="hero-text mb-3">
            {{ heroText }}
          </p>

          <div class="d-flex flex-wrap gap-2">
            <router-link to="/lessons" class="btn btn-primary btn-lg px-4">
              <i class="fa-solid fa-book-open me-2"></i>
              Open Lessons
            </router-link>

            <router-link to="/profile" class="btn btn-outline-dark btn-lg px-4">
              <i class="fa-solid fa-user me-2"></i>
              My Profile
            </router-link>
          </div>
        </div>

        <div class="col-12 col-lg-4">
          <div class="hero-side-card">
            <template v-if="role !== 'ADMIN'">
              <div class="mini-label">Current role</div>
              <div class="mini-value mb-4">
                {{ role }}
              </div>
            </template>

            <!-- ADMIN: jedna kartica umesto "Pending approvals" + "Notifications" -->
            <template v-if="role === 'ADMIN'">
              <div class="mini-label">Zahtevi za registraciju</div>

              <div class="mini-value text-warning mb-1">
                {{ pendingUsers.length }}
              </div>

              <div class="mini-label mb-3">
                {{ pendingUsers.length > 0 ? 'Nalozi čekaju odobrenje.' : 'Nema novih zahteva.' }}
              </div>

              <router-link
                to="/admin/users"
                class="btn btn-warning btn-sm w-100"
              >
                <i class="fa-solid fa-user-check me-2"></i>
                Pregledaj zahteve
              </router-link>
            </template>

            <template v-else>
              <div class="mini-label">
                {{ role === 'TEACHER'
                    ? 'Teaching language'
                    : 'Learning language'
                }}
              </div>

              <div class="mini-value">
                {{ subjectNames || 'Not selected yet' }}
              </div>
            </template>
          </div>
        </div>
      </div>
    </div>

    <div v-if="loading" class="text-muted">Loading...</div>

    <div v-else>
      <div v-if="aiCards.length" class="row g-4 mb-4">
        <div v-for="card in aiCards" :key="card.key" class="col-12 col-md-6">
          <router-link :to="card.to" class="text-decoration-none">
            <div class="dashboard-card stat-card h-100" :class="card.cls">
              <div class="stat-icon"><i :class="card.icon"></i></div>
              <div class="stat-title">{{ card.title }}</div>
              <div class="stat-number">{{ card.value }}</div>
              <div class="stat-text">{{ card.text }}</div>
            </div>
          </router-link>
        </div>
      </div>

      <div class="dashboard-card p-4 mb-4">
        <div class="section-title mb-3">Lessons by Level</div>

        <div class="chart-box">
          <Pie
            :data="levelChartData"
            :options="levelChartOptions"
          />
        </div>
      </div>
    
      <!-- ADMIN -->
      <template v-if="role === 'ADMIN'">
        <div class="row g-4 mb-4">
          <div class="col-12 col-md-4">
            <div class="dashboard-card stat-card stat-blue h-100">
              <div class="stat-icon"><i class="fa-solid fa-globe"></i></div>
              <div class="stat-title">Languages</div>
              <div class="stat-number">{{ languages.length }}</div>
              <div class="stat-text">Registered languages</div>
            </div>
          </div>

          <div class="col-12 col-md-4">
            <div class="dashboard-card stat-card stat-purple h-100">
              <div class="stat-icon"><i class="fa-solid fa-book-open"></i></div>
              <div class="stat-title">Lessons</div>
              <div class="stat-number">{{ lessons.length }}</div>
              <div class="stat-text">Available lessons</div>
            </div>
          </div>

          <div class="col-12 col-md-4">
            <div class="dashboard-card stat-card stat-green h-100">
              <div class="stat-icon"><i class="fa-solid fa-users"></i></div>
              <div class="stat-title">Users</div>
              <div class="stat-number">{{ users.length }}</div>
              <div class="stat-text">Registered accounts</div>
            </div>
          </div>

          
        </div>

        <div class="dashboard-card p-4">
          <div class="section-title mb-3">Quick actions</div>

          <div class="row g-3">
            <div class="col-12 col-md-4">
              <router-link to="/admin/languages" class="action-card text-decoration-none">
                <div class="action-icon"><i class="fa-solid fa-globe"></i></div>
                <div class="action-title">Manage Languages</div>
                <div class="action-text">Add and organize languages</div>
              </router-link>
            </div>

            <div class="col-12 col-md-4">
              <router-link to="/admin/users" class="action-card text-decoration-none">
                <div class="action-icon"><i class="fa-solid fa-users-gear"></i></div>
                <div class="action-title">Manage Users</div>
                <div class="action-text">Approve and manage accounts</div>
              </router-link>
            </div>

            <div class="col-12 col-md-4">
              <router-link to="/lessons" class="action-card text-decoration-none">
                <div class="action-icon"><i class="fa-solid fa-file-lines"></i></div>
                <div class="action-title">Open Lessons</div>
                <div class="action-text">View all available lessons</div>
              </router-link>
            </div>
          </div>
        </div>
      </template>

      <!-- TEACHER -->
      <template v-else-if="role === 'TEACHER'">
        <div class="row g-4 mb-4">
          <div class="col-12 col-md-6">
            <div class="dashboard-card stat-card stat-purple h-100">
              <div class="action-icon"><i class="fa-solid fa-book-open me-2"></i></div>
              <div class="stat-title">Lessons</div>
              <div class="stat-number">{{ lessons.length }}</div>
              <div class="stat-text">Current lesson count</div>
            </div>
          </div>

          <div class="col-12 col-md-6">
            <div class="dashboard-card stat-card stat-green h-100">
              <div class="stat-icon"><i class="fa-solid fa-chalkboard-user"></i></div>
              <div class="stat-title">Role</div>
              <div class="stat-number">TEACHER</div>
              <div class="stat-text">Lesson management access</div>
            </div>
          </div>
        </div>

        <div class="dashboard-card p-4">
          <div class="section-title mb-3">Quick actions</div>

          <div class="row g-3">
            <div class="col-12 col-md-6">
              <router-link to="/lessons" class="action-card text-decoration-none">
                <div class="action-icon"><i class="fa-solid fa-book-open-reader"></i></div>
                <div class="action-title">View Lessons</div>
                <div class="action-text">
                  View lessons for your language
                </div>
              </router-link>
            </div>

            <div class="col-12 col-md-6">
              <router-link to="/manage/lessons" class="action-card text-decoration-none">
                <div class="action-icon"><i class="fa-solid fa-pen-to-square"></i></div>
                <div class="action-title">Manage Lessons</div>
                <div class="action-text">
                  Manage lessons for your language
                </div>
              </router-link>
            </div>
          </div>
        </div>
      </template>

      <!-- STUDENT -->
      <template v-else>
        <div class="row g-4 mb-4">
          <div class="col-12 col-md-4">
            <div class="dashboard-card stat-card stat-blue h-100">
              <div class="stat-icon"><i class="fa-solid fa-globe"></i></div>
              <div class="stat-title">My Language</div>
              <div class="stat-number small-number">
                {{ subjectNames || 'Not selected' }}
              </div>
              <div class="stat-text">Current learning language</div>
            </div>
          </div>

          <div class="col-12 col-md-4">
            <div class="dashboard-card stat-card stat-green h-100">
              <div class="stat-icon"><i class="fa-solid fa-book"></i></div>
              <div class="stat-title">Lessons</div>
              <div class="stat-number">{{ lessons.length }}</div>
              <div class="stat-text">Available lessons</div>
            </div>
          </div>
          <div class="col-12 col-md-4">
            <div class="dashboard-card stat-card stat-orange h-100">
              <div class="stat-icon"><i class="fa-solid fa-star"></i></div>
              <div class="stat-title">Favorites</div>
              <div class="stat-number">
                {{ favorites.length }}
              </div>
              <div class="stat-text">
                Saved lessons
              </div>
            </div>
          </div>
        </div>
        <div class="dashboard-card p-4 mb-4">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <div>
              <div class="section-title">Learning Progress</div>
              <div class="text-muted small">
                {{ progress.length }} of {{ lessons.length }} lessons viewed
              </div>
            </div>

            <div class="progress-percent">
              {{ progressPercent }}%
            </div>
          </div>

          <div class="progress progress-custom">
            <div
              class="progress-bar"
              role="progressbar"
              :style="{ width: progressPercent + '%' }"
              :aria-valuenow="progressPercent"
              aria-valuemin="0"
              aria-valuemax="100"
            >
            </div>
          </div>
        </div>
        
        <div class="dashboard-card p-4">
          <div class="section-title mb-3">Quick actions</div>

          <div class="row g-3">
            <div class="col-12 col-md-4">
              <router-link to="/lessons" class="action-card text-decoration-none">
                <div class="action-icon"><i class="fa-solid fa-book-open me-2"></i></div>
                <div class="action-title">View Lessons</div>
                <div class="action-text">Start learning now</div>
              </router-link>
            </div>

            <div class="col-12 col-md-4">
              <router-link to="/profile" class="action-card text-decoration-none">
                <div class="action-icon"><i class="fa-solid fa-gear"></i></div>
                <div class="action-title">My Profile</div>
                <div class="action-text">
                  View your account information
                </div>
              </router-link>
            </div>
            <div class="col-12 col-md-4">
              <router-link to="/favorites" class="action-card text-decoration-none">
                <div class="stat-icon"><i class="fa-solid fa-star"></i></div>
                <div class="action-title">My Favorites</div>
                <div class="action-text">
                  Open saved lessons
                </div>
              </router-link>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
  <div v-if="needsLanguageChoice" class="language-modal-backdrop">
    <div class="language-modal-card">
      <div class="modal-icon"><i class="fa-solid fa-globe"></i></div>

      <h3 class="fw-bold mb-2">
        Izbor jezika
      </h3>

      <p class="text-muted mb-4">
        {{ languageQuestion }}
      </p>

      <div v-if="languageChoiceError" class="alert alert-danger py-2">
        {{ languageChoiceError }}
      </div>

      <select v-model="selected_language_ids" class="form-select mb-3" multiple size="5">
        <option v-for="s in subjects" :key="s.id" :value="s.id">
          {{ s.name }}
        </option>
      </select>
      <small class="text-muted d-block mb-3">
        Drži Ctrl (ili Cmd) da izabereš više predmeta odjednom.
      </small>

      <button
        class="btn btn-primary w-100"
        :disabled="savingLanguage"
        @click="saveLanguageChoice"
      >
        <span
          v-if="savingLanguage"
          class="spinner-border spinner-border-sm me-2"
        ></span>

        <i v-if="!savingLanguage" class="fa-solid fa-floppy-disk me-2"></i>
        Save 
      </button>
    </div>
  </div>
</template>

<style scoped>
.hero-box {
  background: linear-gradient(135deg, #ffffff 0%, #eef4ff 100%);
  border-radius: 24px;
  padding: 32px;
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
}

.hero-badge {
  display: inline-block;
  background: #212529;
  color: white;
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 0.85rem;
  font-weight: 600;
}

.hero-title {
  font-size: 2.4rem;
  font-weight: 800;
  color: #1f2937;
}

.hero-text {
  font-size: 1.05rem;
  color: #6b7280;
  max-width: 700px;
}

.hero-side-card {
  background: rgba(255, 255, 255, 0.85);
  border-radius: 20px;
  padding: 24px;
  box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.06);
}

.mini-label {
  font-size: 0.85rem;
  color: #6b7280;
  margin-bottom: 4px;
}

.mini-value {
  font-size: 1.2rem;
  font-weight: 800;
  color: #111827;
}

.dashboard-card {
  background: white;
  border-radius: 22px;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
}

.stat-card {
  padding: 24px;
  color: white;
  overflow: hidden;
  position: relative;
}

.stat-blue {
  background: linear-gradient(135deg, #2563eb, #3b82f6);
}

.stat-purple {
  background: linear-gradient(135deg, #7c3aed, #8b5cf6);
}

.stat-orange {
  background: linear-gradient(135deg, #ea580c, #f97316);
}

.stat-green {
  background: linear-gradient(135deg, #059669, #10b981);
}

.stat-icon {
  font-size: 2rem;
  margin-bottom: 12px;
}

.stat-title {
  font-size: 1rem;
  font-weight: 600;
  opacity: 0.95;
}

.stat-number {
  font-size: 2rem;
  font-weight: 800;
  margin: 6px 0;
}

.small-number {
  font-size: 1.4rem;
}

.stat-text {
  opacity: 0.9;
}

.section-title {
  font-size: 1.2rem;
  font-weight: 700;
  color: #1f2937;
}

.action-card {
  display: block;
  background: #f8fafc;
  border-radius: 18px;
  padding: 20px;
  height: 100%;
  transition: all 0.18s ease;
  border: 1px solid #e5e7eb;
}

.action-card:hover {
  transform: translateY(-3px);
  background: white;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
}

.action-icon {
  font-size: 1.7rem;
  margin-bottom: 10px;
}

.action-title {
  font-size: 1.05rem;
  font-weight: 700;
  color: #111827;
  margin-bottom: 4px;
}

.action-text {
  color: #6b7280;
  font-size: 0.95rem;
}

.language-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.language-modal-card {
  background: white;
  width: 100%;
  max-width: 430px;
  border-radius: 24px;
  padding: 32px;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.25);
  text-align: center;
}

.modal-icon {
  font-size: 3rem;
  margin-bottom: 12px;
}
.hero-language {
  font-size: 1rem;
  font-weight: 600;
  color: #2563eb;
}
.progress-custom {
  height: 14px;
  border-radius: 999px;
  background: #e5e7eb;
  overflow: hidden;
}

.progress-custom .progress-bar {
  border-radius: 999px;
  background: linear-gradient(135deg, #2563eb, #10b981);
}

.progress-percent {
  font-size: 1.6rem;
  font-weight: 800;
  color: #2563eb;
}

.chart-box {
  height: 280px;
  max-width: 420px;
  margin: 0 auto;
}
</style>