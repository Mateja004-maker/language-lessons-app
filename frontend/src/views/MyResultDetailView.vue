<script setup>
import PageHeader from '@/components/PageHeader.vue'
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getMyResultDetail, getQuestionExplanation, rateExplanationArtifact } from '@/services/api'
import { formatDbDate } from '@/services/explanationHelpers'

const route = useRoute()
const router = useRouter()

const attemptId = route.params.attemptId

const attempt = ref(null)
const questions = ref([])
const loading = ref(false)
const error = ref('')
const errorStatus = ref(null)

// Stanje objasnjenja po pitanju (question_id -> {...}); objasnjenje se ucitava
// tek kad student otvori deo "Objasnjenje".
const explanations = reactive({})

function answerStatus(q) {
  if (q.is_correct === null) return { cls: 'bg-secondary', icon: 'fa-minus', text: 'Bez odgovora' }
  if (q.is_correct) return { cls: 'bg-success', icon: 'fa-check', text: 'Tačno' }
  return { cls: 'bg-danger', icon: 'fa-xmark', text: 'Netačno' }
}

async function loadAttempt() {
  error.value = ''
  errorStatus.value = null
  loading.value = true
  try {
    const { data } = await getMyResultDetail(attemptId)
    attempt.value = data.attempt
    questions.value = data.questions
    for (const q of data.questions) {
      if (q.explanation_artifact_id) {
        explanations[q.question_id] = {
          open: false,
          loading: false,
          loaded: false,
          error: '',
          content: null,
          rubric: [],
          scores: {},
          submitting: false,
          submitError: '',
          rated: q.already_rated,
          justRated: false
        }
      }
    }
  } catch (e) {
    errorStatus.value = e?.response?.status || null
    error.value = e?.response?.data?.error || 'Ne mogu da učitam detalje rezultata.'
  } finally {
    loading.value = false
  }
}

async function toggleExplanation(q) {
  const state = explanations[q.question_id]
  state.open = !state.open
  if (!state.open || state.loaded || state.loading) return

  state.loading = true
  state.error = ''
  try {
    const { data } = await getQuestionExplanation(q.question_id, q.explanation_mode)
    state.content = data.content
    state.rubric = data.rubric_definitions || []
    for (const criterion of state.rubric) {
      state.scores[criterion.dimension_key] = null
    }
    state.loaded = true
  } catch (e) {
    state.error = e?.response?.data?.error || 'Ne mogu da učitam objašnjenje.'
  } finally {
    state.loading = false
  }
}

function allScored(state) {
  return state.rubric.length > 0 && state.rubric.every((c) => state.scores[c.dimension_key] !== null)
}

async function submitRating(q) {
  const state = explanations[q.question_id]
  if (state.submitting || !allScored(state)) return
  state.submitError = ''
  state.submitting = true
  try {
    await rateExplanationArtifact(
      q.explanation_artifact_id,
      Object.entries(state.scores).map(([dimension_key, score]) => ({ dimension_key, score }))
    )
    state.rated = true
    state.justRated = true
  } catch (e) {
    if (e?.response?.status === 409) {
      state.rated = true
    } else {
      state.submitError = e?.response?.data?.error || 'Ne mogu da sačuvam ocenu.'
    }
  } finally {
    state.submitting = false
  }
}

function goBack() {
  router.push('/my-results')
}

onMounted(loadAttempt)
</script>

<template>
  <div class="container py-4">
    <button class="btn btn-outline-secondary btn-sm mb-3" @click="goBack">
      <i class="fa-solid fa-arrow-left me-2"></i>
      Nazad na rezultate
    </button>

    <div v-if="loading" class="d-flex align-items-center gap-2 text-muted">
      <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
      Učitavanje...
    </div>

    <div v-else-if="error" class="alert alert-danger">
      <strong v-if="errorStatus">[{{ errorStatus }}]</strong>
      {{ error }}
    </div>

    <div v-else-if="attempt">
      <PageHeader :title="attempt.title" />

      <div class="d-flex flex-wrap align-items-center gap-2 mb-4">
        <span class="badge bg-dark">{{ attempt.score }} / {{ attempt.total }} poena</span>
        <span class="text-muted small">{{ formatDbDate(attempt.submitted_at) }}</span>
      </div>

      <div v-if="!questions.length" class="alert alert-info">Ovaj test nema pitanja.</div>

      <div v-for="(q, idx) in questions" :key="q.question_id" class="card shadow-sm mb-3">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start gap-2">
            <div class="fw-semibold pre-wrap">{{ idx + 1 }}. {{ q.question_text }}</div>
            <span class="badge flex-shrink-0" :class="answerStatus(q).cls">
              <i class="fa-solid me-1" :class="answerStatus(q).icon"></i>
              {{ answerStatus(q).text }}
            </span>
          </div>

          <div class="mt-2 text-muted small">
            <template v-if="q.answered">
              Vaš odgovor: <span class="text-body">{{ q.student_answer_text ?? '—' }}</span>
              · {{ q.points_awarded }} / {{ q.points }} poena
            </template>
            <template v-else>Niste odgovorili na ovo pitanje · 0 / {{ q.points }} poena</template>
          </div>

          <div v-if="explanations[q.question_id]" class="mt-3">
            <button class="btn btn-outline-secondary btn-sm" @click="toggleExplanation(q)">
              <i class="fa-solid fa-lightbulb me-1"></i>
              Objašnjenje
              <i class="fa-solid ms-1" :class="explanations[q.question_id].open ? 'fa-chevron-up' : 'fa-chevron-down'"></i>
            </button>

            <div v-if="explanations[q.question_id].open" class="explanation-box mt-2 p-3 border rounded">
              <div v-if="explanations[q.question_id].loading" class="d-flex align-items-center gap-2 text-muted">
                <span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
                Učitavanje...
              </div>

              <div v-else-if="explanations[q.question_id].error" class="alert alert-danger mb-0">
                {{ explanations[q.question_id].error }}
              </div>

              <template v-else-if="explanations[q.question_id].content">
                <template v-if="explanations[q.question_id].content.solution">
                  <div class="fw-semibold mb-1">Rešenje</div>
                  <pre class="bg-light border rounded p-2 mb-3 code-block">{{ explanations[q.question_id].content.solution }}</pre>
                </template>
                <p class="mb-3 pre-wrap">{{ explanations[q.question_id].content.explanation }}</p>

                <div v-if="explanations[q.question_id].rated" class="alert alert-success mb-0">
                  <i class="fa-solid fa-check me-2"></i>
                  {{ explanations[q.question_id].justRated ? 'Hvala, vaša ocena je sačuvana.' : 'Već ste ocenili ovo objašnjenje.' }}
                </div>

                <div v-else class="border-top pt-3">
                  <div class="fw-semibold mb-2">Koliko vam je ovo objašnjenje pomoglo?</div>

                  <div
                    v-for="criterion in explanations[q.question_id].rubric"
                    :key="criterion.dimension_key"
                    class="d-flex flex-wrap justify-content-between align-items-center gap-2 py-2"
                  >
                    <div>{{ criterion.dimension_label }}</div>

                    <div class="btn-group btn-group-sm" role="group">
                      <template v-for="n in (criterion.scale_max - criterion.scale_min + 1)" :key="n">
                        <input
                          type="radio"
                          class="btn-check"
                          :id="`rate-${q.question_id}-${criterion.dimension_key}-${criterion.scale_min + n - 1}`"
                          :name="`rate-${q.question_id}-${criterion.dimension_key}`"
                          :checked="explanations[q.question_id].scores[criterion.dimension_key] === criterion.scale_min + n - 1"
                          @change="explanations[q.question_id].scores[criterion.dimension_key] = criterion.scale_min + n - 1"
                        />
                        <label
                          class="btn btn-outline-primary"
                          :for="`rate-${q.question_id}-${criterion.dimension_key}-${criterion.scale_min + n - 1}`"
                        >
                          {{ criterion.scale_min + n - 1 }}
                        </label>
                      </template>
                    </div>
                  </div>

                  <div v-if="explanations[q.question_id].submitError" class="alert alert-danger mt-2 mb-2">
                    {{ explanations[q.question_id].submitError }}
                  </div>

                  <button
                    class="btn btn-primary btn-sm mt-2"
                    :disabled="!allScored(explanations[q.question_id]) || explanations[q.question_id].submitting"
                    @click="submitRating(q)"
                  >
                    <span v-if="explanations[q.question_id].submitting" class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>
                    {{ explanations[q.question_id].submitting ? 'Čuvam...' : 'Pošalji ocenu' }}
                  </button>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pre-wrap {
  white-space: pre-wrap;
}

.code-block {
  font-family: var(--bs-font-monospace);
  white-space: pre-wrap;
  word-break: break-word;
}

.explanation-box {
  background: var(--app-bg);
}
</style>
