<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/services/api'
import { logout } from '@/services/auth'

const router = useRouter()

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

function onLogout() {
  logout()
  router.push('/login')
}
</script>

<template>
  <nav class="navbar navbar-expand-lg navbar-dark bg-dark shadow-sm">
    <div class="container">

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

        <ul class="navbar-nav me-auto mb-2 mb-lg-0">

          <li class="nav-item">
            <router-link class="nav-link" to="/">
              Home
            </router-link>
          </li>

          <li
            v-if="isLoggedIn"
            class="nav-item d-flex align-items-center me-2"
          >
            <span
              v-if="role === 'ADMIN'"
              class="badge text-bg-danger"
            >
              ADMIN
            </span>

            <span
              v-else-if="role === 'TEACHER'"
              class="badge text-bg-warning"
            >
              TEACHER
            </span>

            <span
              v-else
              class="badge text-bg-success"
            >
              STUDENT
            </span>
          </li>

          <li v-if="isLoggedIn" class="nav-item">
            <router-link class="nav-link" to="/lessons">
              Lessons
            </router-link>
          </li>

          <li
            v-if="isLoggedIn && isStudent"
            class="nav-item"
          >
            <router-link class="nav-link" to="/favorites">
              Favorites
            </router-link>
          </li>

          <li
            v-if="isLoggedIn && canManageLessons"
            class="nav-item"
          >
            <router-link class="nav-link" to="/manage/lessons">
              Manage Lessons
            </router-link>
          </li>
          <li
            v-if="isLoggedIn && (role === 'TEACHER' || role === 'ADMIN')"
            class="nav-item"
          >
            <router-link class="nav-link" to="/exams">
              Exams
            </router-link>
          </li>
          <li
            v-if="isLoggedIn && canManageLessons"
            class="nav-item"
          >
            <router-link class="nav-link" to="/predmeti">
              Predmeti
            </router-link>
          </li>
          <router-link
          v-if="isLoggedIn && role === 'STUDENT'"
          class="nav-link"
          to="/exams"
        >
          Exams
        </router-link>
          <router-link
          v-if="isLoggedIn && isStudent"
          class="nav-link"
          to="/my-results"
        >
          My Results
        </router-link>

          <li class="nav-item">
            <router-link class="nav-link" to="/profile">
              My Profile
            </router-link>
          </li>

          <li
            v-if="isAdmin"
            class="nav-item"
          >
            <router-link class="nav-link" to="/admin/users">
              Users
            </router-link>
          </li>

          <li
            v-if="isLoggedIn && isAdmin"
            class="nav-item"
          >
            <router-link class="nav-link" to="/admin/languages">
              Languages
            </router-link>
          </li>

        </ul>

        <div class="d-flex align-items-center gap-3">

          <div
            v-if="isLoggedIn"
            class="user-box"
          >
            <div class="user-avatar">
              <img
                v-if="profile?.profile_image"
                :src="`http://127.0.0.1:5000${profile.profile_image}`"
                alt="Profile"
                class="navbar-profile-img"
              />

              <span v-else>
                {{ profile?.display_name?.charAt(0)?.toUpperCase() || 'U' }}
              </span>
            </div>

            <div class="user-info">
              <div class="user-name">
                {{ profile?.display_name || 'User' }}
              </div>

              <div class="user-role">
                {{ role }}
              </div>
            </div>
          </div>

          <router-link
            v-if="!isLoggedIn"
            class="btn btn-outline-primary btn-sm"
            to="/login"
          >
            Login
          </router-link>

          <button
            v-else
            class="logout-btn"
            type="button"
            @click="onLogout"
            title="Logout"
          >
            <i class="bi bi-box-arrow-right"></i>
          </button>

        </div>

      </div>
    </div>
  </nav>
</template>

<style scoped>
.custom-navbar {
  background: linear-gradient(90deg, #111827 0%, #1f2937 100%);
  box-shadow: 0 8px 22px rgba(0, 0, 0, 0.12);
}

.navbar-brand {
  font-size: 1.6rem;
  font-weight: 800;
}

.nav-link {
  font-weight: 500;
}

.nav-link.router-link-active {
  color: #ffffff !important;
}

.role-pill {
  border-radius: 999px;
  padding: 6px 12px;
  font-weight: 700;
}

.user-box {
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(255, 255, 255, 0.08);
  padding: 6px 12px;
  border-radius: 14px;
}

.user-avatar {
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
.logout-btn {
  width: 42px;
  height: 42px;
  border: none;
  border-radius: 12px;
  background: rgba(255,255,255,0.08);
  color: white;
  font-size: 1.1rem;
  transition: all 0.18s ease;
}

.logout-btn:hover {
  background: rgba(255,255,255,0.18);
  transform: translateY(-1px);
}
.navbar-profile-img {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
}
</style>