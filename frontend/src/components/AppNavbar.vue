<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { logout } from '@/services/auth'

const router = useRouter()

const token = computed(() => localStorage.getItem('access_token'))
const role = computed(() => localStorage.getItem('user_role'))

const isLoggedIn = computed(() => !!token.value)
const isAdmin = computed(() => role.value === 'ADMIN')
const canManageLessons = computed(() => role.value === 'TEACHER' || role.value === 'ADMIN')

function onLogout() {
  logout()
  router.push('/login')
}
</script>

<template>
  <nav class="nav">
    <div class="left">
      <router-link class="brand" to="/">Language Lessons</router-link>

      <router-link v-if="isLoggedIn" class="link" to="/">Lessons</router-link>

      <router-link
        v-if="isLoggedIn && canManageLessons"
        class="link"
        to="/manage/lessons"
      >
        Manage Lessons
      </router-link>

      <router-link
        v-if="isLoggedIn && isAdmin"
        class="link"
        to="/admin/languages"
      >
        Admin Languages
      </router-link>
    </div>

    <div class="right">
      <span v-if="isLoggedIn" class="role">Role: <b>{{ role }}</b></span>
      <router-link v-if="!isLoggedIn" class="link" to="/login">Login</router-link>
      <button v-else class="btn" @click="onLogout">Logout</button>
    </div>
  </nav>
</template>

<style scoped>
.nav {
  position: sticky;
  top: 0;
  z-index: 1000;

  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;

  padding: 12px 20px;

  /* nova boja (plavo-ljubičasta) */
  background: linear-gradient(90deg, #1e3a8a, #6d28d9);
  border-bottom: 1px solid rgba(255,255,255,0.15);
  color: #fff;
}

.left, .right {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.brand {
  font-weight: 800;
  color: #fff;
  text-decoration: none;
  letter-spacing: 0.2px;
}

.link {
  color: rgba(255,255,255,0.92);
  text-decoration: none;
  padding: 6px 10px;
  border-radius: 10px;
}

.link:hover {
  background: rgba(255,255,255,0.16);
}

.role {
  opacity: 0.95;
  background: rgba(0,0,0,0.18);
  padding: 6px 10px;
  border-radius: 10px;
}

.btn {
  padding: 8px 12px;
  border-radius: 10px;
  border: 0;
  cursor: pointer;

  background: rgba(255,255,255,0.92);
  color: #111;
  font-weight: 600;
}
</style>