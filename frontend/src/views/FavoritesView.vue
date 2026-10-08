<script setup>
import { onMounted, ref } from 'vue'
import { api } from '@/services/api'

const favorites = ref([])
const loading = ref(false)
const error = ref('')

function stripHtml(html) {
  const div = document.createElement('div')
  div.innerHTML = html || ''
  return div.textContent || div.innerText || ''
}

async function loadFavorites() {
  error.value = ''
  loading.value = true

  try {
    const { data } = await api.get('/favorites')
    favorites.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Failed to load favorites.'
  } finally {
    loading.value = false
  }
}

async function removeFavorite(id) {
  try {
    await api.delete(`/lessons/${id}/favorite`)
    await loadFavorites()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Failed to remove favorite.'
  }
}

onMounted(loadFavorites)
</script>

<template>
  <div class="container py-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <div>
        <div class="page-title">My Favorites</div>
        <div class="page-subtitle">
          Saved lessons for quick access
        </div>
      </div>

      <button class="btn btn-outline-secondary btn-sm" @click="loadFavorites">
        Refresh
      </button>
    </div>

    <div v-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <div v-if="loading" class="section-card section-padding text-muted">
      Loading favorites...
    </div>

    <div v-else-if="favorites.length === 0" class="section-card section-padding text-center">
      <div class="stat-icon"><i class="fa-solid fa-star"></i></div>
      <h5 class="mb-1">No favorite lessons yet.</h5>
      <p class="text-muted mb-0">
        Add lessons to favorites from the Lessons page.
      </p>
    </div>

    <div v-else class="row g-3">
      <div
        v-for="lesson in favorites"
        :key="lesson.id"
        class="col-12 col-lg-6"
      >
        <div class="card favorite-card">
          <div class="card-body p-3">
            <div class="d-flex justify-content-between align-items-start mb-2">
              <div>
                <div class="lesson-kicker mb-1">
                  {{ lesson.language_code?.toUpperCase() || 'LANGUAGE' }}
                </div>

                <h5 class="card-title mb-2">
                  {{ lesson.title }}
                </h5>

                <div class="d-flex gap-2 flex-wrap mb-2">
                  <span class="badge text-bg-primary">
                    {{ lesson.level }}
                  </span>

                  <span class="badge text-bg-light border">
                    Favorite
                  </span>
                </div>
              </div>

              <div class="stat-icon"><i class="fa-solid fa-star"></i></div>
            </div>

            <p class="lesson-preview mb-3">
              {{ stripHtml(lesson.content).slice(0, 120) || 'No lesson description available.' }}
              <span v-if="stripHtml(lesson.content).length > 120">...</span>
            </p>

            <div class="d-flex justify-content-between align-items-center gap-2">
              <router-link
                :to="`/lessons/${lesson.id}`"
                class="btn btn-primary btn-sm"
              >
                Open lesson
              </router-link>

              <button
                class="btn btn-outline-danger btn-sm"
                @click="removeFavorite(lesson.id)"
              >
                Remove
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

  </div>
</template>

<style scoped>
.favorite-card {
  border: none;
  border-radius: 18px;
  box-shadow: var(--app-shadow);
}

.lesson-kicker {
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--app-accent-text);
}

.card-title {
  font-size: 1.3rem;
  font-weight: 800;
}

.favorite-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: var(--app-accent-soft);
  font-size: 1.1rem;
}

.lesson-preview {
  color: var(--app-text-muted);
  line-height: 1.5;
  font-size: 0.97rem;
}

.empty-icon {
  font-size: 2rem;
}
</style>