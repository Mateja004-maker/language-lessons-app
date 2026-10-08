<script setup>
import { onMounted, ref } from 'vue'
import { api } from '@/services/api'
import AppIllustration from '@/components/AppIllustration.vue'

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
    error.value = e?.response?.data?.error || 'Učitavanje omiljenih lekcija nije uspelo.'
  } finally {
    loading.value = false
  }
}

async function removeFavorite(id) {
  try {
    await api.delete(`/lessons/${id}/favorite`)
    await loadFavorites()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Uklanjanje iz omiljenih nije uspelo.'
  }
}

onMounted(loadFavorites)
</script>

<template>
  <div class="container py-4">
    <div class="page-header">
      <div>
        <h1 class="page-title">Omiljene lekcije</h1>
        <p class="page-subtitle">Sačuvane lekcije za brz pristup</p>
      </div>

      <button class="btn btn-outline-secondary btn-sm" @click="loadFavorites">
        Osveži
      </button>
    </div>

    <div v-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <div v-if="loading" class="section-card section-padding text-muted">
      Učitavanje omiljenih lekcija...
    </div>

    <div v-else-if="favorites.length === 0" class="section-card empty-state">
      <AppIllustration kind="star" class="mb-2" />
      <h5 class="mb-1">Još nemaš omiljenih lekcija.</h5>
      <p class="text-muted mb-0">
        Dodaj lekcije u omiljene sa stranice Lekcije.
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
                    Omiljena
                  </span>
                </div>
              </div>

              <div class="stat-icon"><i class="fa-solid fa-star"></i></div>
            </div>

            <p class="lesson-preview mb-3">
              {{ stripHtml(lesson.content).slice(0, 120) || 'Lekcija nema opis.' }}
              <span v-if="stripHtml(lesson.content).length > 120">...</span>
            </p>

            <div class="d-flex justify-content-between align-items-center gap-2">
              <router-link
                :to="`/lessons/${lesson.id}`"
                class="btn btn-primary btn-sm"
              >
                Otvori lekciju
              </router-link>

              <button
                class="btn btn-outline-danger btn-sm"
                @click="removeFavorite(lesson.id)"
              >
                Ukloni
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
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius);
  box-shadow: var(--app-shadow);
}

.lesson-kicker {
  font-size: 0.82rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--app-primary);
}

.card-title {
  font-size: 1.3rem;
  font-weight: 800;
}

/* zvezdica omiljenih u jantarnoj (ukras) */
.stat-icon {
  color: var(--app-amber);
}

.favorite-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: var(--app-primary-soft);
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