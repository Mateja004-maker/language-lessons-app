<script setup>
import { onMounted, ref, computed } from 'vue'
import { api } from '@/services/api'

const lessons = ref([])
const error = ref('')
const loading = ref(false)
const favorites = ref([])

const role = computed(() => localStorage.getItem('user_role') || '')

const isTeacherOrAdmin = computed(() =>
  role.value === 'TEACHER' || role.value === 'ADMIN'
)
const isStudent = computed(() => role.value === 'STUDENT')

function stripHtml(html) {
  const div = document.createElement('div')
  div.innerHTML = html || ''
  return div.textContent || div.innerText || ''
}

function levelClass(level) {
  const l = String(level || '').toUpperCase()

  if (l === 'A1') return 'text-bg-success'
  if (l === 'A2') return 'text-bg-primary'
  if (l === 'B1') return 'text-bg-warning'
  if (l === 'B2') return 'text-bg-info'
  if (l === 'C1' || l === 'C2') return 'text-bg-danger'

  return 'text-bg-secondary'
}
function isFavorite(id) {
  return favorites.value.includes(id)
}

async function load() {
  error.value = ''
  loading.value = true

  try {
    const { data } = await api.get('/lessons')
    lessons.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Učitavanje lekcija nije uspelo.'
  } finally {
    loading.value = false
  }
}
async function loadFavorites() {
  if (!isStudent.value) return

  try {
    const { data } = await api.get('/favorites')
    favorites.value = data.map(f => f.id)
  } catch (e) {
    console.error(e)
  }
}

async function deleteLesson(id) {
  const confirmed = confirm('Da li sigurno želiš da obrišeš ovu lekciju?')
  if (!confirmed) return

  try {
    await api.delete(`/lessons/${id}`)
    await load()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Brisanje lekcije nije uspelo.'
  }
}

async function addFavorite(id) {
  try {
    await api.post(`/lessons/${id}/favorite`)
    await loadFavorites()
  } catch (e) {
    console.error(e)
  }
}

async function removeFavorite(id) {
  try {
    await api.delete(`/lessons/${id}/favorite`)
    await loadFavorites()
  } catch (e) {
    console.error(e)
  }
}

onMounted(async () => {
  await load()
  await loadFavorites()
})
</script>

<template>
  <div class="container py-4">

    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <div class="page-title">Lekcije</div>
        <div class="page-subtitle">
          Lekcije iz tvojih predmeta
        </div>
      </div>

      <button
        class="btn btn-outline-secondary btn-sm px-3"
        @click="load"
        :disabled="loading"
      >
        Osveži
      </button>
    </div>

    <div v-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <div v-if="loading" class="section-card section-padding text-muted">
      Učitavanje lekcija...
    </div>

    <div v-else-if="lessons.length === 0" class="section-card section-padding text-center">
      <div class="empty-icon mb-2">📚</div>
      <h5 class="mb-1">Nema dostupnih lekcija.</h5>
      <p class="text-muted mb-0">
        Kada nastavnik doda lekcije, pojaviće se ovde.
      </p>
    </div>

    <div v-else class="row g-3">
      <div
        class="col-12 col-lg-6"
        v-for="(lesson, index) in lessons"
        :key="lesson.id"
      >
        <div class="card lesson-card">

          <router-link
            :to="`/lessons/${lesson.id}`"
            class="text-decoration-none text-dark"
          >
            <div class="card-body p-3">

              <div class="d-flex justify-content-between align-items-start mb-2">
                <div>
                  <div class="lesson-kicker mb-1">
                    {{ lesson.language_code?.toUpperCase() || 'LEKCIJA' }}
                  </div>

                  <h5 class="card-title mb-2">
                    {{ lesson.title }}
                  </h5>

                  <div class="d-flex gap-2 flex-wrap mb-2">
                    <span
                      class="badge"
                      :class="levelClass(lesson.level)"
                    >
                      {{ lesson.level || 'Nivo' }}
                    </span>

                    <span class="badge text-bg-light border">
                      Lekcija #{{ index + 1 }}
                    </span>
                  </div>
                </div>

                <div class="lesson-icon">
                  🗣️
                </div>
              </div>

              <p class="lesson-preview mb-2">
                {{ stripHtml(lesson.content).slice(0, 120) || 'Lekcija nema opis.' }}
                <span v-if="stripHtml(lesson.content).length > 120">...</span>
              </p>

              <div class="lesson-footer">
                Otvori lekciju →
              </div>
              <div
                v-if="isStudent"
                class="mt-3"
              >
                <button
                  v-if="!isFavorite(lesson.id)"
                  class="btn btn-outline-warning btn-sm"
                  @click.prevent="addFavorite(lesson.id)"
                >
                  ☆ Dodaj u omiljene
                </button>

                <button
                  v-else
                  class="btn btn-warning btn-sm"
                  @click.prevent="removeFavorite(lesson.id)"
                >
                  ★ Ukloni iz omiljenih
                </button>
              </div>

            </div>
          </router-link>

          <div
            v-if="isTeacherOrAdmin"
            class="card-footer bg-white border-0 px-3 pb-3 pt-0 text-end"
          >
            <button
              class="btn btn-outline-danger btn-sm"
              @click.stop="deleteLesson(lesson.id)"
            >
              Obriši
            </button>
          </div>

        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.lesson-card {
  border: none;
  border-radius: 18px;
  box-shadow: 0 8px 22px rgba(15, 23, 42, 0.06);
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease;
  overflow: hidden;
  
}

.lesson-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.10);
}

.lesson-kicker {
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #6366f1;
}

.lesson-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: #eef2ff;
  font-size: 1.1rem;
}

.card-title {
  font-size: 1.35rem;
  font-weight: 800;
}

.lesson-preview {
  color: #4b5563;
  line-height: 1.5;
  font-size: 0.97rem;

  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;

  overflow: hidden;
}

.lesson-footer {
  color: #2563eb;
  font-weight: 700;
  font-size: 0.95rem;
}

.badge {
  font-size: 0.78rem;
  padding: 6px 10px;
}

.empty-icon {
  font-size: 2rem;
}
</style>