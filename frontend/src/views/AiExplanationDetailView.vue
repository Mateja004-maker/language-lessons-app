<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getExplanationArtifact, getQuestionAnswers, reviewExplanationArtifact } from '@/services/api'
import { buildEditedText, formatDbDate, parseAccuracyDetails, parseProposal } from '@/services/explanationHelpers'

const route = useRoute()
const router = useRouter()

const artifactId = route.params.id

const STATUS_LABELS = {
  predlog: 'Na čekanju',
  prihvaceno: 'Prihvaćeno',
  prihvaceno_izmena: 'Prihvaćeno uz izmenu',
  odbaceno: 'Odbačeno'
}

const artifact = ref(null)
const rubric = ref([])
const answers = ref([])
const loading = ref(false)
const error = ref('')
const errorStatus = ref(null)

const scores = reactive({})
const comment = ref('')

const submitting = ref(false)
const submitError = ref('')

const showEditForm = ref(false)
const editExplanation = ref('')
const editSolution = ref('')

const showRejectForm = ref(false)
const rejectReason = ref('')

const proposal = computed(() => parseProposal(artifact.value?.original_text))
const editedProposal = computed(() => parseProposal(artifact.value?.edited_text))
const accuracy = computed(() => parseAccuracyDetails(artifact.value?.accuracy_check_details))
const isModeB = computed(() => artifact.value?.mode === 'mode_b')
const isPending = computed(() => artifact.value?.status === 'predlog')

// Tacnost resenja u rezimu B je eliminacioni kriterijum: ako mehanicka provera
// nije prosla, backend dozvoljava samo odbacivanje.
const onlyRejectAllowed = computed(() => isModeB.value && artifact.value?.accuracy_check_passed === 0)

const allScored = computed(() => {
  if (!rubric.value.length) return false
  return rubric.value.every((c) => scores[c.dimension_key] !== null && scores[c.dimension_key] !== undefined)
})

async function loadArtifact() {
  error.value = ''
  errorStatus.value = null
  loading.value = true
  try {
    const { data } = await getExplanationArtifact(artifactId)
    artifact.value = data.artifact
    rubric.value = data.rubric_definitions || []
    for (const criterion of rubric.value) {
      scores[criterion.dimension_key] = null
    }
    if (data.artifact?.source_question_id) {
      const res = await getQuestionAnswers(data.artifact.source_question_id)
      answers.value = res.data || []
    }
  } catch (e) {
    errorStatus.value = e?.response?.status || null
    error.value = e?.response?.data?.error || 'Ne mogu da učitam predlog objašnjenja.'
  } finally {
    loading.value = false
  }
}

function setScore(dimensionKey, value) {
  scores[dimensionKey] = value
}

// Kod odbijanja ocene su opcione - salju se samo one koje su unete.
function buildScoresPayload() {
  const text = comment.value.trim() || undefined
  return Object.entries(scores)
    .filter(([, score]) => score !== null && score !== undefined)
    .map(([dimension_key, score]) => ({ dimension_key, score, comment: text }))
}

async function submitReview(data) {
  if (submitting.value) return
  submitError.value = ''
  submitting.value = true
  try {
    await reviewExplanationArtifact(artifactId, data)
    router.push('/ai/objasnjenja')
  } catch (e) {
    submitError.value = e?.response?.data?.error || 'Ne mogu da sačuvam pregled.'
    submitting.value = false
  }
}

function approve() {
  submitReview({ action: 'approve', scores: buildScoresPayload() })
}

function openEditForm() {
  submitError.value = ''
  showRejectForm.value = false
  editExplanation.value = proposal.value?.explanation || ''
  editSolution.value = proposal.value?.solution || ''
  showEditForm.value = true
}

function cancelEdit() {
  showEditForm.value = false
}

function approveWithEdit() {
  // edited_text mora biti JSON string istog oblika kao original - studentska
  // ruta ga parsira; zato se oblik proverava ovde, pre slanja.
  const built = buildEditedText(artifact.value.mode, {
    explanation: editExplanation.value,
    solution: editSolution.value
  })
  if (built.error) {
    submitError.value = built.error
    return
  }
  submitReview({ action: 'edit', scores: buildScoresPayload(), edited_text: built.text })
}

function openRejectForm() {
  submitError.value = ''
  showEditForm.value = false
  rejectReason.value = ''
  showRejectForm.value = true
}

function cancelReject() {
  showRejectForm.value = false
}

function reject() {
  submitReview({
    action: 'reject',
    scores: buildScoresPayload(),
    rejection_reason: rejectReason.value.trim()
  })
}

function goBack() {
  router.push('/ai/objasnjenja')
}

onMounted(loadArtifact)
</script>

<template>
  <div class="container py-4">
    <button class="btn btn-outline-secondary btn-sm mb-3" @click="goBack">
      <i class="fa-solid fa-arrow-left me-2"></i>
      Nazad na listu
    </button>

    <div v-if="loading" class="d-flex align-items-center gap-2 text-muted">
      <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
      Učitavanje...
    </div>

    <div v-else-if="error" class="alert alert-danger">
      <strong v-if="errorStatus">[{{ errorStatus }}]</strong>
      {{ error }}
    </div>

    <div v-else-if="artifact">
      <h2 class="page-title mb-2">AI objašnjenje #{{ artifact.id }}</h2>

      <div class="d-flex flex-wrap align-items-center gap-2 mb-4">
        <span class="badge bg-info text-dark">{{ isModeB ? 'Režim B' : 'Režim A' }}</span>
        <span class="badge bg-secondary">{{ STATUS_LABELS[artifact.status] || artifact.status }}</span>
        <span v-if="answers.length" class="badge bg-light text-dark border">MC</span>
        <!-- Slepo ocenjivanje: vreme generisanja se ne prikazuje dok je predlog u statusu 'predlog' -->
        <span v-if="artifact.status !== 'predlog' && artifact.created_at" class="text-muted small">{{ formatDbDate(artifact.created_at) }}</span>
      </div>

      <div class="row g-3 mb-4">
        <div class="col-12 col-lg-6">
          <div class="card shadow-sm h-100">
            <div class="card-header bg-white">
              <i class="fa-solid fa-file-lines me-2 text-muted"></i>
              Pitanje
            </div>
            <div class="card-body">
              <p class="mb-3 pre-wrap">{{ artifact.question_text }}</p>

              <div v-if="answers.length">
                <div
                  v-for="a in answers"
                  :key="a.id"
                  class="d-flex justify-content-between align-items-center border rounded p-2 mb-2"
                >
                  <span>{{ a.answer_text }}</span>
                  <span v-if="a.is_correct" class="badge bg-success">Tačan</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="col-12 col-lg-6">
          <div class="card shadow-sm h-100 border-primary">
            <div class="card-header bg-primary bg-opacity-10">
              <i class="fa-solid fa-lightbulb me-2 text-primary"></i>
              AI predlog
            </div>
            <div class="card-body">
              <div v-if="!proposal" class="alert alert-warning mb-0">
                Predlog nije u očekivanom JSON obliku i ne može da se prikaže.
              </div>

              <template v-else>
                <template v-if="isModeB">
                  <div class="fw-semibold mb-1">Rešenje</div>
                  <pre class="bg-light border rounded p-2 mb-3 code-block">{{ proposal.solution }}</pre>
                  <div class="fw-semibold mb-1">Objašnjenje</div>
                </template>
                <p class="mb-0 pre-wrap">{{ proposal.explanation }}</p>
              </template>
            </div>
          </div>
        </div>
      </div>

      <div v-if="isModeB" class="card shadow-sm mb-4">
        <div class="card-header bg-white">
          <i class="fa-solid fa-vial me-2 text-muted"></i>
          Mehanička provera rešenja
          <span v-if="artifact.accuracy_check_passed === 1" class="badge bg-success ms-2">prošla</span>
          <span v-else-if="artifact.accuracy_check_passed === 0" class="badge bg-danger ms-2">nije prošla</span>
          <span v-else class="badge bg-warning text-dark ms-2">nije izvršena</span>
        </div>
        <div class="card-body">
          <div v-if="accuracy.rows" class="table-responsive">
            <table class="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Ulaz</th>
                  <th>Očekivano</th>
                  <th>Dobijeno</th>
                  <th>Rezultat</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in accuracy.rows" :key="row.order_no">
                  <td>{{ row.order_no }}</td>
                  <td><pre class="mb-0 code-cell">{{ row.input_data }}</pre></td>
                  <td><pre class="mb-0 code-cell">{{ row.expected_output }}</pre></td>
                  <td><pre class="mb-0 code-cell">{{ row.actual_output ?? '—' }}</pre></td>
                  <td>
                    <span v-if="row.passed" class="badge bg-success">tačno</span>
                    <template v-else>
                      <span class="badge bg-danger">{{ row.timed_out ? 'isteklo vreme' : 'netačno' }}</span>
                      <pre v-if="row.error" class="mb-0 mt-1 small text-danger code-cell">{{ row.error }}</pre>
                    </template>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else-if="accuracy.message" class="text-muted">{{ accuracy.message }}</div>
          <div v-else class="text-muted">Nema podataka o proveri.</div>
        </div>
      </div>

      <div v-if="!isPending" class="card shadow-sm mb-4">
        <div class="card-body">
          <p class="mb-2">
            Ovaj predlog je već pregledan ({{ STATUS_LABELS[artifact.status] || artifact.status }}<span v-if="artifact.reviewed_at">, {{ formatDbDate(artifact.reviewed_at) }}</span>).
          </p>
          <div v-if="artifact.rejection_reason" class="text-muted">Razlog odbijanja: {{ artifact.rejection_reason }}</div>
          <div v-if="editedProposal">
            <div class="fw-semibold mt-2 mb-1">Izmenjena verzija</div>
            <pre v-if="editedProposal.solution" class="bg-light border rounded p-2 mb-2 code-block">{{ editedProposal.solution }}</pre>
            <p class="mb-0 pre-wrap">{{ editedProposal.explanation }}</p>
          </div>
        </div>
      </div>

      <template v-else>
        <div v-if="onlyRejectAllowed" class="alert alert-info">
          <i class="fa-solid fa-circle-info me-2"></i>
          Mehanička provera rešenja nije prošla. Tačnost rešenja je eliminacioni kriterijum,
          pa je za ovaj predlog jedina moguća odluka <strong>„Odbaci“</strong>.
          Ocene po rubrici su kod odbijanja opcione.
        </div>

        <div class="card shadow-sm mb-4">
          <div class="card-header bg-white">
            <i class="fa-solid fa-list-check me-2 text-muted"></i>
            Ocena po kriterijumima rubrike
          </div>
          <div class="card-body">
            <div
              v-for="criterion in rubric"
              :key="criterion.dimension_key"
              class="d-flex flex-wrap justify-content-between align-items-center gap-2 border-bottom py-3"
            >
              <div class="fw-semibold">{{ criterion.dimension_label }}</div>

              <div class="btn-group" role="group">
                <template v-for="n in (criterion.scale_max - criterion.scale_min + 1)" :key="n">
                  <input
                    type="radio"
                    class="btn-check"
                    :id="`criterion-${criterion.dimension_key}-${criterion.scale_min + n - 1}`"
                    :name="`criterion-${criterion.dimension_key}`"
                    :checked="scores[criterion.dimension_key] === criterion.scale_min + n - 1"
                    @change="setScore(criterion.dimension_key, criterion.scale_min + n - 1)"
                  />
                  <label
                    class="btn btn-outline-primary"
                    :for="`criterion-${criterion.dimension_key}-${criterion.scale_min + n - 1}`"
                  >
                    {{ criterion.scale_min + n - 1 }}
                  </label>
                </template>
              </div>
            </div>

            <div class="mt-3">
              <label class="form-label">Komentar (opciono)</label>
              <textarea v-model="comment" class="form-control" rows="3"></textarea>
            </div>
          </div>
        </div>

        <div v-if="showEditForm" class="card shadow-sm mb-4 border-warning">
          <div class="card-header bg-warning bg-opacity-25">
            <i class="fa-solid fa-pen me-2"></i>
            Izmena predloga pre prihvatanja
          </div>
          <div class="card-body">
            <div v-if="isModeB" class="mb-3">
              <label class="form-label">Rešenje</label>
              <textarea v-model="editSolution" class="form-control code-block" rows="6"></textarea>
              <div class="form-text">Izmenjeno rešenje se ne proverava ponovo automatski.</div>
            </div>

            <div class="mb-2">
              <label class="form-label">Objašnjenje</label>
              <textarea v-model="editExplanation" class="form-control" rows="8"></textarea>
            </div>

            <div class="d-flex gap-2 mt-3">
              <button class="btn btn-secondary btn-sm" :disabled="submitting" @click="cancelEdit">
                Otkaži izmenu
              </button>
            </div>
          </div>
        </div>

        <div v-if="showRejectForm" class="card shadow-sm mb-4 border-danger">
          <div class="card-header bg-danger bg-opacity-25">
            <i class="fa-solid fa-xmark me-2"></i>
            Razlog odbijanja
          </div>
          <div class="card-body">
            <div class="mb-2">
              <label class="form-label">Zašto se predlog odbija? (obavezno)</label>
              <textarea v-model="rejectReason" class="form-control" rows="3"></textarea>
            </div>

            <div class="d-flex gap-2 mt-3">
              <button class="btn btn-secondary btn-sm" :disabled="submitting" @click="cancelReject">
                Otkaži
              </button>
            </div>
          </div>
        </div>

        <div class="card shadow-sm">
          <div class="card-body">
            <div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

            <div v-if="!onlyRejectAllowed && !allScored" class="text-muted small mb-2">
              Oceni sve kriterijume rubrike da bi mogao da prihvatiš predlog (kod odbijanja su ocene opcione).
            </div>

            <div class="d-flex flex-wrap gap-2">
              <template v-if="!onlyRejectAllowed">
                <button
                  class="btn btn-success"
                  :disabled="!allScored || !proposal || submitting"
                  @click="approve"
                >
                  <span v-if="submitting" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                  <i v-else class="fa-solid fa-check me-2"></i>
                  {{ submitting ? 'Čuvam...' : 'Prihvati bez izmene' }}
                </button>

                <button
                  v-if="!showEditForm"
                  class="btn btn-outline-warning"
                  :disabled="!allScored || !proposal || submitting"
                  @click="openEditForm"
                >
                  <i class="fa-solid fa-pen me-2"></i>
                  Prihvati uz izmenu
                </button>

                <button
                  v-else
                  class="btn btn-warning"
                  :disabled="!allScored || submitting"
                  @click="approveWithEdit"
                >
                  <span v-if="submitting" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                  <i v-else class="fa-solid fa-check me-2"></i>
                  {{ submitting ? 'Čuvam...' : 'Sačuvaj sa izmenom' }}
                </button>
              </template>

              <button
                v-if="!showRejectForm"
                class="btn btn-outline-danger"
                :disabled="submitting"
                @click="openRejectForm"
              >
                <i class="fa-solid fa-xmark me-2"></i>
                Odbaci
              </button>

              <button
                v-else
                class="btn btn-danger"
                :disabled="submitting || !rejectReason.trim()"
                @click="reject"
              >
                <span v-if="submitting" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                <i v-else class="fa-solid fa-xmark me-2"></i>
                {{ submitting ? 'Čuvam...' : 'Potvrdi odbijanje' }}
              </button>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.page-title {
  font-size: 2rem;
  font-weight: 800;
}

.pre-wrap {
  white-space: pre-wrap;
}

.code-block {
  font-family: var(--bs-font-monospace);
  white-space: pre-wrap;
  word-break: break-word;
}

.code-cell {
  font-family: var(--bs-font-monospace);
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 0.85em;
}
</style>
