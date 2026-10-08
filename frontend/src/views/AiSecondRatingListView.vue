<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSecondRatingList } from '@/services/api'
import AppIllustration from '@/components/AppIllustration.vue'

// Druga ocena (slepo, bez odluke): predlozi iz otvorenih evaluacionih serija
// koje ovaj ocenjivač još nije ocenio - nasumičan, stabilan uzorak.
const route = useRoute()
const router = useRouter()

const items = ref([])
const loading = ref(false)
const error = ref('')
const saved = ref(route.query.sacuvano ? `Ocena za predlog #${route.query.sacuvano} je sačuvana.` : '')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await getSecondRatingList()
    items.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam predloge za drugu ocenu.'
  } finally {
    loading.value = false
  }
}

function questionTypeLabel(item) {
  return item.question_type === 'mc' ? 'MC' : 'Otvoreno pitanje'
}

onMounted(load)
</script>

<template>
  <div class="container py-4">
    <h2 class="page-title mb-1">Druga ocena AI predloga</h2>
    <p class="text-muted mb-4">
      Ocena po rubrici bez donošenja odluke, radi saglasnosti ocenjivača. Model, odluka i tuđe ocene se ne
      prikazuju dok ne predaš svoju ocenu ili dok se serija ne zatvori.
    </p>

    <div v-if="saved" class="alert alert-success">{{ saved }}</div>

    <div v-if="loading" class="d-flex align-items-center gap-2 text-muted">
      <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
      Učitavanje...
    </div>

    <div v-else-if="error" class="alert alert-warning">{{ error }}</div>

    <div v-else-if="!items.length" class="text-muted text-center py-5">
      <AppIllustration kind="scale" class="mb-3 d-block mx-auto" />
      Nema predloga za drugu ocenu.
    </div>

    <div v-else>
      <div
        v-for="item in items"
        :key="item.id"
        class="card shadow-sm mb-3 rating-card"
        @click="router.push(`/ai/druga-ocena/${item.id}`)"
      >
        <div class="card-body">
          <div>
            <i class="fa-solid fa-scale-balanced me-2 text-muted"></i>
            {{ item.original_text?.question_text }}
          </div>
          <div class="d-flex flex-wrap align-items-center gap-2 mt-2">
            <span class="badge bg-dark">{{ item.subject_name || 'Nepoznat predmet' }}</span>
            <span v-if="item.area_name" class="badge bg-secondary">{{ item.area_name }}</span>
            <span class="badge bg-info text-dark">{{ questionTypeLabel(item) }}</span>
            <span class="badge bg-light text-dark border">serija #{{ item.batch_id }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page-title {
  font-size: 2rem;
  font-weight: 800;
}

.rating-card {
  cursor: pointer;
}

.rating-card:hover {
  box-shadow: var(--app-shadow-hover) !important;
}
</style>
