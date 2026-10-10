<script setup>
import PageHeader from '@/components/PageHeader.vue'
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getAiArtifacts, getSubjects } from '@/services/api'
import AppIllustration from '@/components/AppIllustration.vue'
import ProposalGroups from '@/components/ProposalGroups.vue'

const router = useRouter()
const route = useRoute()

// grupe su zatvorene kad se stranica otvori; ?pitanje=<id originalnog pitanja> otvara samo tu grupu
const openQuestion = route.query.pitanje ? String(route.query.pitanje) : null
const groupsRef = ref(null)

const artifacts = ref([])
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
const filteredArtifacts = computed(() =>
  selectedSubject.value
    ? artifacts.value.filter(a => Number(a.subject_id) === Number(selectedSubject.value))
    : artifacts.value
)

function questionTypeLabel(artifact) {
  return artifact.question_type === 'mc' ? 'MC' : 'Otvoreno pitanje'
}

async function loadArtifacts() {
  error.value = ''
  loading.value = true
  try {
    const { data } = await getAiArtifacts('predlog')
    artifacts.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam AI predloge.'
  } finally {
    loading.value = false
  }
  // izabrano pitanje iz adrese: skrol do njegove (otvorene) grupe
  if (openQuestion) {
    await nextTick()
    const group = document.querySelector(`[data-group-key="${CSS.escape(openQuestion)}"]`)
    if (group) window.scrollTo({ top: group.getBoundingClientRect().top + window.scrollY - 16 })
  }
}

function openArtifact(artifact) {
  router.push(`/ai/predlozi/${artifact.id}`)
}

onMounted(() => {
  loadArtifacts()
  loadSubjects()
})
</script>

<template>
  <div class="container py-4">
    <PageHeader title="AI predlozi" />

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-if="loading" class="d-flex align-items-center gap-2 text-muted">
      <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
      Učitavanje...
    </div>

    <div v-else-if="!artifacts.length" class="section-card empty-state">
      <AppIllustration kind="inbox" class="mb-3 d-block mx-auto" />
      Nema predloga na čekanju.
    </div>

    <div v-else>
      <!-- filter neposredno iznad liste -->
      <div class="table-toolbar">
        <h5 class="m-0">Predlozi na čekanju</h5>
        <div class="d-flex flex-wrap align-items-center gap-2">
          <button type="button" class="btn btn-outline-secondary btn-sm" @click="groupsRef?.openAll()">Otvori sve</button>
          <button type="button" class="btn btn-outline-secondary btn-sm" @click="groupsRef?.closeAll()">Zatvori sve</button>
          <select v-model="selectedSubject" class="form-select" aria-label="Predmet">
            <option value="">Svi predmeti</option>
            <option v-for="s in subjects" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </div>
      </div>

      <div v-if="!filteredArtifacts.length" class="text-muted">Nema predloga za izabrani predmet.</div>

      <ProposalGroups ref="groupsRef" :items="filteredArtifacts" :initially-open="false" :open-key="openQuestion">
        <template #item="{ item: artifact }">
          <div
            class="card shadow-sm mb-3 artifact-card"
            @click="openArtifact(artifact)"
          >
            <div class="card-body">
              <div class="d-flex justify-content-between align-items-start">
                <div>
                  <i class="fa-solid fa-wand-magic-sparkles me-2 text-muted"></i>
                  {{ artifact.original_text?.question_text }}
                </div>
              </div>

              <div class="d-flex flex-wrap align-items-center gap-2 mt-2">
                <span class="badge bg-dark">{{ artifact.subject_name || 'Nepoznat predmet' }}</span>
                <span v-if="artifact.area_name" class="badge bg-secondary">{{ artifact.area_name }}</span>
                <span class="badge bg-info text-dark">{{ questionTypeLabel(artifact) }}</span>
                <!-- Mogući duplikat (sličnost teksta; ne otkriva model) -->
                <span
                  v-if="artifact.possible_duplicate"
                  class="badge bg-warning text-dark"
                  :title="artifact.similar_source === 'artifact' ? 'Sličan drugom AI predlogu' : 'Sličan pitanju iz banke'"
                >
                  <i class="fa-solid fa-clone me-1"></i>
                  mogući duplikat ({{ Math.round(artifact.max_similarity * 100) }} % sa {{ artifact.similar_question_id ? '#' + artifact.similar_question_id : 'drugim predlogom' }})
                </span>
                <!-- Slepo ocenjivanje: model se ne prikazuje dok je predlog u statusu 'predlog' -->
                <span v-if="artifact.status !== 'predlog' && artifact.model_name" class="badge bg-light text-dark border">{{ artifact.provider }} / {{ artifact.model_name }}</span>
              </div>
            </div>
          </div>
        </template>
      </ProposalGroups>
    </div>
  </div>
</template>

<style scoped>
.artifact-card {
  cursor: pointer;
  transition: box-shadow 0.15s ease, transform 0.15s ease;
}

.artifact-card:hover {
  box-shadow: var(--app-shadow-hover) !important;
  transform: translateY(-1px);
}

</style>