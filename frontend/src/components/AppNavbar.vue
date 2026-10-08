<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/services/api'
import { logout } from '@/services/auth'

const router = useRouter()
const route = useRoute()

const token = computed(() => localStorage.getItem('access_token'))
const role = computed(() => localStorage.getItem('user_role'))

const profile = ref(null)

async function loadProfile() {
  if (!localStorage.getItem('access_token')) return

  try {
    const { data } = await api.get('/profile')
    profile.value = data
  } catch (e) {
    profile.value = null
  }
}

onMounted(loadProfile)

const isLoggedIn = computed(() => !!token.value)
const isAdmin = computed(() => role.value === 'ADMIN')
const isStudent = computed(() => role.value === 'STUDENT')

const canManageLessons = computed(() =>
  role.value === 'TEACHER' || role.value === 'ADMIN'
)

// padajući meni je istaknut kad je otvorena neka od njegovih stranica
const isAiRoute = computed(() => route.path.startsWith('/ai/'))
const isAdminRoute = computed(() => route.path.startsWith('/admin/'))

function onLogout() {
  logout()
  router.push('/login')
}
</script>

<template>
  <nav class="navbar navbar-expand-xl navbar-dark bg-dark shadow-sm">
    <div class="container nav-container">

      <router-link class="navbar-brand" to="/">
        Language Lessons
      </router-link>

      <button
        class="navbar-toggler"
        type="button"
        data-bs-toggle="collapse"
        data-bs-target="#nav"
        aria-controls="nav"
        aria-expanded="false"
        aria-label="Toggle navigation"
      >
        <span class="navbar-toggler-icon"></span>
      </button>

      <div id="nav" class="collapse navbar-collapse">

        <ul class="navbar-nav me-auto mb-2 mb-xl-0">

          <li class="nav-item">
            <router-link class="nav-link" to="/">
              Home
            </router-link>
          </li>

          <li v-if="isLoggedIn" class="nav-item">
            <router-link class="nav-link" to="/lessons">
              Lessons
            </router-link>
          </li>

          <li v-if="isLoggedIn && isStudent" class="nav-item">
            <router-link class="nav-link" to="/favorites">
              Favorites
            </router-link>
          </li>

          <li v-if="isLoggedIn && canManageLessons" class="nav-item">
            <router-link class="nav-link" to="/manage/lessons">
              Manage Lessons
            </router-link>
          </li>

          <!-- ista ruta za sve uloge (ranije dve stavke: TEACHER/ADMIN i STUDENT) -->
          <li v-if="isLoggedIn && (canManageLessons || isStudent)" class="nav-item">
            <router-link class="nav-link" to="/exams">
              Exams
            </router-link>
          </li>

          <li v-if="isLoggedIn && isStudent" class="nav-item">
            <router-link class="nav-link" to="/my-results">
              My Results
            </router-link>
          </li>

          <li v-if="isLoggedIn && canManageLessons" class="nav-item">
            <router-link class="nav-link" to="/predmeti">
              Predmeti
            </router-link>
          </li>

          <li v-if="isLoggedIn && canManageLessons" class="nav-item dropdown">
            <a
              class="nav-link dropdown-toggle"
              :class="{ active: isAiRoute }"
              href="#"
              role="button"
              data-bs-toggle="dropdown"
              aria-expanded="false"
            >
              AI
            </a>
            <ul class="dropdown-menu dropdown-menu-dark">
              <li><router-link class="dropdown-item" to="/ai/predlozi">AI predlozi</router-link></li>
              <li><router-link class="dropdown-item" to="/ai/druga-ocena">Druga ocena</router-link></li>
              <li><router-link class="dropdown-item" to="/ai/objasnjenja">AI objašnjenja</router-link></li>
            </ul>
          </li>

          <li v-if="isLoggedIn && isAdmin" class="nav-item dropdown">
            <a
              class="nav-link dropdown-toggle"
              :class="{ active: isAdminRoute }"
              href="#"
              role="button"
              data-bs-toggle="dropdown"
              aria-expanded="false"
            >
              Administracija
            </a>
            <ul class="dropdown-menu dropdown-menu-dark">
              <li><router-link class="dropdown-item" to="/admin/users">Users</router-link></li>
              <li><router-link class="dropdown-item" to="/admin/languages">Languages</router-link></li>
            </ul>
          </li>

        </ul>

        <div class="d-flex align-items-center gap-3">

          <div v-if="isLoggedIn" class="dropdown">
            <button
              class="user-box dropdown-toggle"
              type="button"
              data-bs-toggle="dropdown"
              aria-expanded="false"
            >
              <span class="user-avatar">
                <img
                  v-if="profile?.profile_image"
                  :src="`http://127.0.0.1:5000${profile.profile_image}`"
                  alt="Profile"
                  class="navbar-profile-img"
                />

                <span v-else>
                  {{ profile?.display_name?.charAt(0)?.toUpperCase() || 'U' }}
                </span>
              </span>

              <span class="user-info">
                <span class="user-name">
                  {{ profile?.display_name || 'User' }}
                </span>

                <span class="user-role">
                  {{ role }}
                </span>
              </span>
            </button>

            <ul class="dropdown-menu dropdown-menu-end dropdown-menu-dark">
              <li>
                <router-link class="dropdown-item" to="/profile">
                  <i class="bi bi-person me-2"></i>My Profile
                </router-link>
              </li>
              <li><hr class="dropdown-divider" /></li>
              <li>
                <button class="dropdown-item" type="button" title="Logout" @click="onLogout">
                  <i class="bi bi-box-arrow-right me-2"></i>Logout
                </button>
              </li>
            </ul>
          </div>

          <router-link
            v-else
            class="btn btn-outline-primary btn-sm"
            to="/login"
          >
            Login
          </router-link>

        </div>

      </div>
    </div>
  </nav>
</template>

<style scoped>
/* Globalni .container u main.css je 1100px - za navbar je preusko (stavke su
   se lomile u dva reda i izlazile van trake). Važi samo za navbar. */
.nav-container {
  max-width: 1320px;
}

.navbar-brand {
  font-size: 1.6rem;
  font-weight: 800;
}

.nav-link {
  font-weight: 500;
  white-space: nowrap;
}

.nav-link.router-link-active {
  color: #ffffff !important;
}

.user-box {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.08);
  padding: 6px 12px;
  border: none;
  border-radius: 14px;
  color: white;
  text-align: left;
}

.user-box:hover {
  background: rgba(255, 255, 255, 0.16);
}

.user-info,
.user-name,
.user-role {
  display: block;
}

.user-avatar {
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: #3b82f6;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
}

.user-info {
  line-height: 1.1;
}

.user-name {
  color: white;
  font-size: 0.92rem;
  font-weight: 700;
}

.user-role {
  color: rgba(255, 255, 255, 0.7);
  font-size: 0.75rem;
}
.navbar-profile-img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
}
</style>