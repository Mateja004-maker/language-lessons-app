<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '@/services/api'

const route = useRoute()
const lesson = ref(null)
const error = ref('')
const loading = ref(false)

const role = localStorage.getItem('user_role')
const viewedLessons = ref([])

async function loadLesson() {
  error.value = ''
  loading.value = true

  try {
    const { data } = await api.get(`/lessons/${route.params.id}`)
    lesson.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam lekciju.'
  } finally {
    loading.value = false
  }
}

async function loadProgress() {
  if (role !== 'STUDENT') return

  try {
    const { data } = await api.get('/progress')
    viewedLessons.value = data.map(p => p.lesson_id)
  } catch (e) {
    console.error(e)
  }
}

function isViewed() {
  return viewedLessons.value.includes(Number(route.params.id))
}

async function markViewed() {
  try {
    await api.post(`/progress/${route.params.id}`)
    await loadProgress()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da označim lekciju kao pogledanu.'
  }
}

async function unmarkViewed() {
  try {
    await api.delete(`/progress/${route.params.id}`)
    await loadProgress()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da uklonim oznaku.'
  }
}


onMounted(async () => {
  await loadLesson()
  await loadProgress()
})
</script>

<template>
  <div class="container py-4">
    <div v-if="loading" class="text-muted">Loading...</div>
    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-if="lesson" class="lesson-card">
      <div class="lesson-header">
        <div>
          <h1 class="page-title">{{ lesson.title }}</h1>
          <p class="page-subtitle">
            {{ lesson.language_code?.toUpperCase() }} • {{ lesson.level }}
          </p>
        </div>
        <div v-if="role === 'STUDENT'" class="viewed-actions">
          <button
            v-if="!isViewed()"
            class="btn btn-outline-success btn-sm"
            @click="markViewed"
          >
            Mark as viewed
          </button>

          <button
            v-else
            class="btn btn-success btn-sm"
            @click="unmarkViewed"
          >
            Viewed ✓
          </button>
        </div>
      </div>

      <div class="lesson-content" v-html="lesson.content"></div>

      <div class="lesson-extra-grid">
        <div v-if="lesson.tips" class="extra-card tips-card">
          <h5>Tips & Tricks</h5>
          <p>{{ lesson.tips }}</p>
        </div>

        <div v-if="lesson.important_info" class="extra-card important-card">
          <h5>Important Information</h5>
          <p>{{ lesson.important_info }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.container {
  max-width: 1000px;
}

.lesson-card {
  background: var(--app-surface);
  border-radius: var(--app-radius);
  padding: 34px;
  box-shadow: var(--app-shadow);
}

.lesson-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding-bottom: 18px;
  margin-bottom: 24px;
  border-bottom: 1px solid var(--app-border);
}

.lesson-content {
  font-size: 1.05rem;
  line-height: 1.8;
  color: var(--app-text);
}

.lesson-content :deep(h1),
.lesson-content :deep(h2),
.lesson-content :deep(h3) {
  margin-top: 22px;
  margin-bottom: 12px;
  color: var(--app-text);
  font-weight: 700;
}

.lesson-content :deep(p) {
  margin-bottom: 14px;
}

.lesson-content :deep(ul),
.lesson-content :deep(ol) {
  padding-left: 26px;
  margin-bottom: 16px;
}

.lesson-content :deep(img) {
  max-width: 100%;
  border-radius: 16px;
  margin: 16px 0;
}

.lesson-extra-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
  margin-top: 30px;
}

.extra-card {
  border-radius: var(--app-radius);
  padding: 20px;
  background: var(--app-bg);
  border: 1px solid var(--app-border);
}

.extra-card h5 {
  margin-bottom: 10px;
  font-weight: 700;
}

.extra-card p {
  margin: 0;
  line-height: 1.6;
  color: var(--app-text);
  white-space: pre-line;
}

/* bez obojenih ivica: razlika samo u svetloj pozadini */
.tips-card {
  background: var(--app-primary-soft);
}

.important-card {
  background: var(--app-danger-soft);
}

@media (max-width: 768px) {
  .lesson-card {
    padding: 22px;
  }

  .lesson-extra-grid {
    grid-template-columns: 1fr;
  }
}
</style>