<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getSubjects } from '@/services/api'

const router = useRouter()

const subjects = ref([])
const loading = ref(false)
const error = ref('')

async function load() {
  error.value = ''
  loading.value = true
  try {
    const { data } = await getSubjects()
    subjects.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam predmete.'
  } finally {
    loading.value = false
  }
}

function openSubject(subject) {
  router.push({ name: 'subject-areas', params: { subjectId: subject.id } })
}

onMounted(load)
</script>

<template>
  <div class="container py-4">
    <h2 class="page-title mb-4">Predmeti</h2>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="loading">Učitavanje...</div>

    <div v-else class="row row-cols-1 row-cols-md-3 g-3">
      <div v-for="subject in subjects" :key="subject.id" class="col">
        <div class="card subject-card shadow-sm h-100" @click="openSubject(subject)">
          <div class="card-body">
            <h5 class="card-title mb-1">
              <i class="fa-solid fa-book me-2"></i>
              {{ subject.name }}
            </h5>
            <div class="text-muted small">{{ subject.code }}</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.subject-card {
  cursor: pointer;
  transition: transform 0.1s ease, box-shadow 0.1s ease;
}

.subject-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--app-shadow-hover) !important;
}
</style>
