<script setup>
import { onMounted, ref } from 'vue'
import { api } from '@/services/api'
import { logout } from '@/services/auth'
import { useRouter } from 'vue-router'

const router = useRouter()
const lessons = ref([])
const error = ref('')
const role = localStorage.getItem('user_role')

async function load() {
  error.value = ''
  try {
    const { data } = await api.get('/lessons')
    lessons.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Failed to load lessons'
  }
}

function onLogout() {
  logout()
  router.push('/login')
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="topbar">
      <h2>Lessons</h2>

      <div class="right">
        <span>Role: <b>{{ role }}</b></span>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>

    <div v-else>
      <p v-if="lessons.length === 0">Nema lekcija još.</p>

      <ul v-else class="list">
        <li v-for="l in lessons" :key="l.id" class="list-item">
          <router-link class="lesson-link" :to="`/lessons/${l.id}`">
            <b>{{ l.language_code }}</b> {{ l.level }} — {{ l.title }}
          </router-link>
        </li>
      </ul>

      <p v-if="role === 'ADMIN'" class="admin">
        Idi na:
        <router-link to="/admin/languages">/admin/languages</router-link>
      </p>
    </div>
  </div>
</template>

<style scoped>
/* Ako ti je i dalje "crno", ovo garantuje da je tekst vidljiv */
.page {
  max-width: 900px;
  margin: 30px auto;
  padding: 16px;
  color: #fff;
}

.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn {
  padding: 8px 12px;
  border-radius: 8px;
  border: 0;
  cursor: pointer;
}

.error {
  color: #ff6b6b;
}

.list {
  margin-top: 12px;
  padding-left: 18px;
}

.list-item {
  margin: 8px 0;
}

.lesson-link {
  color: #7db4ff;
  text-decoration: none;
}

.lesson-link:hover {
  text-decoration: underline;
}

.admin {
  margin-top: 14px;
}
</style>
