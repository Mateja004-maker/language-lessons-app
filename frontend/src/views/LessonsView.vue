<script setup>
import PageHeader from '@/components/PageHeader.vue'
import { onMounted, ref, computed } from 'vue'
import { api } from '@/services/api'
import AppIllustration from '@/components/AppIllustration.vue'

const lessons = ref([])
const error = ref('')
const loading = ref(false)
const favorites = ref([])

// filter po predmetu (predmeti iz /api/subjects: ADMIN sve, nastavnik i student svoje).
// Lekcija je vezana za predmet preko subject_id.
const subjects = ref([])
const selectedSubject = ref('')
const filteredLessons = computed(() =>
  selectedSubject.value
    ? lessons.value.filter(l => Number(l.subject_id) === Number(selectedSubject.value))
    : lessons.value
)

async function loadSubjects() {
  try {
    const { data } = await api.get('/subjects')
    subjects.value = data
  } catch (e) {
    subjects.value = []
  }
}

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
  await loadSubjects()
  await loadFavorites()
})
</script>

<template>
  <div class="container py-4">

    <PageHeader title="Lekcije">
      <select v-model="selectedSubject" class="form-select" aria-label="Predmet">
        <option value="">Svi predmeti</option>
        <option v-for="s in subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
      </select>
    </PageHeader>

    <div v-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <div v-if="loading" class="section-card section-padding text-muted">
      Učitavanje lekcija...
    </div>

    <div v-else-if="filteredLessons.length === 0" class="section-card empty-state">
      <AppIllustration kind="book" class="mb-2" />
      <h5 class="mb-1">Nema dostupnih lekcija.</h5>
      <p class="text-muted mb-0">
        Kada nastavnik doda lekcije, pojaviće se ovde.
      </p>
    </div>

    <div v-else class="row g-3">
      <div
        class="col-12 col-lg-6"
        v-for="(lesson, index) in filteredLessons"
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
                    {{ lesson.subject_name?.toUpperCase() || 'LEKCIJA' }}
                    <span v-if="lesson.area_name" class="badge text-bg-light border area-badge">{{ lesson.area_name }}</span>
                  </div>

                  <h5 class="card-title mb-2">
                    {{ lesson.title }}
                  </h5>

                  <div class="d-flex gap-2 flex-wrap mb-2">
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
                  class="btn btn-outline-primary btn-sm"
                  @click.prevent="addFavorite(lesson.id)"
                >
                  ☆ Dodaj u omiljene
                </button>

                <button
                  v-else
                  class="btn btn-primary btn-sm"
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
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  box-shadow: var(--app-shadow);
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease;
  overflow: hidden;
  
}

.lesson-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--app-shadow-hover);
}

.lesson-kicker {
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--app-primary);
}

/* oblast lekcije: sitna oznaka pored predmeta */
.area-badge {
  margin-left: 0.4rem;
  letter-spacing: normal;
  vertical-align: middle;
}

.lesson-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: var(--app-primary-soft);
  font-size: 1.1rem;
}

.card-title {
  font-size: 1.35rem;
  font-weight: 800;
}

.lesson-preview {
  color: var(--app-text-muted);
  line-height: 1.5;
  font-size: 0.97rem;

  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;

  overflow: hidden;
}

.lesson-footer {
  color: var(--app-primary);
  font-weight: 700;
  font-size: 0.95rem;
}

</style>