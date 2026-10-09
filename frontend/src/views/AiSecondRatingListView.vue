<script setup>
import PageHeader from '@/components/PageHeader.vue'
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSecondRatingList, getSubjects } from '@/services/api'
import AppIllustration from '@/components/AppIllustration.vue'
import ProposalGroups from '@/components/ProposalGroups.vue'

// Druga ocena (slepo, bez odluke): predlozi iz otvorenih evaluacionih serija
// koje ovaj ocenjivač još nije ocenio - nasumičan, stabilan uzorak.
const route = useRoute()
const router = useRouter()

const items = ref([])
const loading = ref(false)
const error = ref('')

// filter po predmetu (predmeti iz /api/subjects: ADMIN svi, nastavnik samo svoji)
const subjects = ref([])
const selectedSubject = ref('')
async function loadSubjects() {
  try {
    const { data } = await getSubjects()
    subjects.value = data
  } catch (e) {
    subjects.value = []
  }
}

// filter ne menja (nasumican) redosled sa servera, samo izbacuje druge predmete
const filteredItems = computed(() =>
  selectedSubject.value
    ? items.value.filter(i => Number(i.subject_id) === Number(selectedSubject.value))
    : items.value
)
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

onMounted(() => {
  load()
  loadSubjects()
})
</script>

<template>
  <div class="container py-4">
    <PageHeader title="Druga ocena AI predloga" />

    <div v-if="saved" class="alert alert-success">{{ saved }}</div>

    <div v-if="loading" class="d-flex align-items-center gap-2 text-muted">
      <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
      Učitavanje...
    </div>

    <div v-else-if="error" class="alert alert-warning">{{ error }}</div>

    <div v-else-if="!items.length" class="section-card empty-state">
      <AppIllustration kind="scale" class="mb-3 d-block mx-auto" />
      Nema predloga za drugu ocenu.
    </div>

    <div v-else>
      <!-- filter neposredno iznad liste -->
      <div class="table-toolbar">
        <h5 class="m-0">Predlozi za drugu ocenu</h5>
        <select v-model="selectedSubject" class="form-select" aria-label="Predmet">
          <option value="">Svi predmeti</option>
          <option v-for="s in subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
        </select>
      </div>

      <div v-if="!filteredItems.length" class="text-muted">Nema predloga za izabrani predmet.</div>

      <!-- u ovoj listi su samo predlozi koje jos nisi ocenio -->
      <ProposalGroups :items="filteredItems" :is-rated="() => false">
        <template #item="{ item }">
          <div
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
        </template>
      </ProposalGroups>
    </div>
  </div>
</template>

<style scoped>
.rating-card {
  cursor: pointer;
}

.rating-card:hover {
  box-shadow: var(--app-shadow-hover) !important;
}
</style>
