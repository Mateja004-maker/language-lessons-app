<script>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { getExamDetails, submitExam } from '@/services/api'

export default {
  setup() {
    const route = useRoute()

    const exam = ref(null)
    const answers = ref({})
    const result = ref(null)
    const error = ref('')
    const isSubmitting = ref(false)

    const timeLeft = ref(0)
    const tabWarnings = ref(0)
    const showWarningModal = ref(false)
    const fullscreenRequired = ref(false)

    let timerInterval = null
    const MAX_WARNINGS = 3
    const answeredCount = computed(() => Object.keys(answers.value).length)

    const totalQuestions = computed(() => exam.value?.questions?.length || 0)

    const formattedTime = computed(() => {
      const minutes = Math.floor(timeLeft.value / 60)
      const seconds = timeLeft.value % 60
      return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    })

    const isFullscreen = () => !!document.fullscreenElement

    const playWarningSound = () => {
      try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)()
        const oscillator = audioContext.createOscillator()
        const gainNode = audioContext.createGain()

        oscillator.connect(gainNode)
        gainNode.connect(audioContext.destination)

        oscillator.frequency.value = 800
        oscillator.type = 'sine'
        gainNode.gain.setValueAtTime(0.2, audioContext.currentTime)

        oscillator.start()
        oscillator.stop(audioContext.currentTime + 0.3)
      } catch (err) {
        console.log('Sound error:', err)
      }
    }

    const addWarning = () => {
      if (!exam.value || result.value || isSubmitting.value) return

      tabWarnings.value += 1
      playWarningSound()

      if (tabWarnings.value >= MAX_WARNINGS) {
        submit()
      } else {
        showWarningModal.value = true
      }
    }

    const requestFullscreen = async () => {
      try {
        if (!isFullscreen()) {
          await document.documentElement.requestFullscreen()
        }
        fullscreenRequired.value = false
      } catch (err) {
        fullscreenRequired.value = true
      }
    }

    const handleFullscreenChange = () => {
      if (!exam.value?.exam_mode || result.value || isSubmitting.value) return

      if (!isFullscreen()) {
        fullscreenRequired.value = true
        addWarning()
      }
    }

    const handleVisibilityChange = () => {
      if (!exam.value || result.value || isSubmitting.value) return

      if (document.hidden) {
        addWarning()
      }
    }

    const closeWarningModal = () => {
      showWarningModal.value = false
    }

    const submit = async () => {
      if (isSubmitting.value || result.value) return

      try {
        isSubmitting.value = true

        if (timerInterval) clearInterval(timerInterval)

        const res = await submitExam(route.params.id, {
          answers: answers.value,
          tab_warnings: tabWarnings.value
        })

        result.value = res.data

        if (isFullscreen()) {
          await document.exitFullscreen()
        }
      } catch (err) {
        console.log(err)
        error.value =
          err.response?.data?.error ||
          err.response?.data?.message ||
          'Predaja testa nije uspela.'
      }
    }

    const startTimer = () => {
      if (!exam.value?.duration_minutes) return

      const now = new Date()
      const durationEnd = new Date(now.getTime() + exam.value.duration_minutes * 60 * 1000)
      let finalEnd = durationEnd

      if (exam.value.close_at) {
        const closeAt = new Date(exam.value.close_at)
        if (closeAt < durationEnd) finalEnd = closeAt
      }

      const updateTimer = () => {
        const diff = Math.floor((finalEnd - new Date()) / 1000)
        timeLeft.value = diff > 0 ? diff : 0

        if (timeLeft.value <= 0) {
          clearInterval(timerInterval)
          submit()
        }
      }

      updateTimer()
      timerInterval = setInterval(updateTimer, 1000)
    }

    const loadExam = async () => {
      try {
        const res = await getExamDetails(route.params.id)
        exam.value = res.data

        if (exam.value.exam_mode) {
          fullscreenRequired.value = true
        }

        startTimer()
      } catch (err) {
        error.value = err.response?.data?.error || 'Ovaj test ne možeš da radiš.'
      }
    }

    onMounted(() => {
      loadExam()
      document.addEventListener('visibilitychange', handleVisibilityChange)
      document.addEventListener('fullscreenchange', handleFullscreenChange)
    })

    onUnmounted(() => {
      if (timerInterval) clearInterval(timerInterval)
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      document.removeEventListener('fullscreenchange', handleFullscreenChange)
    })

    return {
      exam,
      answers,
      result,
      submit,
      error,
      isSubmitting,
      timeLeft,
      formattedTime,
      tabWarnings,
      showWarningModal,
      closeWarningModal,
      fullscreenRequired,
      requestFullscreen,
      answeredCount,
      totalQuestions
    }
  }
}
</script>

<template>
  <div class="container py-4">
    <div v-if="error" class="alert alert-danger">
      {{ error }}
    </div>

    <div v-else-if="!exam" class="card">
      <div class="card-body">
        Učitavanje...
      </div>
    </div>

    <div v-else>
      <div
        v-if="fullscreenRequired && !result"
        class="alert alert-danger d-flex justify-content-between align-items-center"
      >
        <div>
          <strong>Ispitni režim je uključen.</strong>
          Za nastavak uključi prikaz preko celog ekrana.
        </div>

        <button class="btn btn-primary" @click="requestFullscreen">
          Ceo ekran
        </button>
      </div>

      <div
        v-if="showWarningModal"
        class="modal fade show d-block"
        tabindex="-1"
        style="background-color: rgba(0, 0, 0, 0.5);"
      >
        <div class="modal-dialog modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header bg-warning">
              <h5 class="modal-title">Upozorenje</h5>
            </div>

            <div class="modal-body">
              <p>
                Sistem je primetio da je promenjen tab u pregledaču, da je napušten prozor testa
                ili da je isključen prikaz preko celog ekrana.
              </p>

              <p>
                Posle 3 upozorenja test se automatski predaje.
              </p>

              <p class="mb-0">
                Ukupno upozorenja:
                <strong>{{ tabWarnings }}</strong>
              </p>
            </div>

            <div class="modal-footer">
              <button class="btn btn-primary" @click="closeWarningModal">
                Razumem
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="card border-0 shadow-sm mb-4 sticky-top" style="top: 1rem; z-index: 10;">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-start flex-wrap gap-3">
            <div>
              <h2 class="h4 mb-1">{{ exam.title }}</h2>

              <div class="text-muted small">
                Trajanje: {{ exam.duration_minutes }} min
                <span class="mx-2">|</span>
                Pitanja: {{ totalQuestions }}
                <span v-if="exam.exam_mode" class="badge bg-dark ms-2">
                  Ispitni režim
                </span>
              </div>
            </div>

            <div class="d-flex gap-2 flex-wrap">
              <div v-if="!result" class="badge bg-warning text-dark fs-6 p-2">
                Preostalo vreme: {{ formattedTime }}
              </div>

              <div
                v-if="!result"
                class="badge bg-primary fs-6 p-2"
              >
                Odgovoreno: {{ answeredCount }} / {{ totalQuestions }}
              </div>

              <div
                v-if="!result && tabWarnings > 0"
                class="badge bg-danger fs-6 p-2"
              >
                Upozorenja: {{ tabWarnings }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="result" class="alert alert-info">
        <h5 class="mb-2">Test je predat</h5>
        <div>Poeni: {{ result.score }} / {{ result.total }}</div>
        <div>Upozorenja: {{ tabWarnings }}</div>
      </div>

      <div v-if="!result">
        <div
          v-for="(question, index) in exam.questions"
          :key="question.id"
          class="card border-0 shadow-sm mb-3"
        >
          <div class="card-body">
            <div class="d-flex justify-content-between align-items-start mb-3">
              <h5 class="mb-0">
                Pitanje {{ index + 1 }}
              </h5>

              <span
                class="badge"
                :class="answers[question.id] ? 'bg-success' : 'bg-secondary'"
              >
                {{ answers[question.id] ? 'Odgovoreno' : 'Bez odgovora' }}
              </span>
            </div>

            <p class="fw-semibold mb-3">
              {{ question.question_text }}
            </p>

            <div
              v-for="answer in question.answers"
              :key="answer.id"
              class="form-check border rounded p-3 mb-2"
            >
              <input
                class="form-check-input ms-0 me-2"
                type="radio"
                :name="'question-' + question.id"
                :value="answer.id"
                v-model="answers[question.id]"
                :disabled="isSubmitting"
              />

              <label class="form-check-label ms-2">
                {{ answer.answer_text }}
              </label>
            </div>
          </div>
        </div>

        <div class="card border-0 shadow-sm mt-4">
          <div class="card-body d-flex justify-content-between align-items-center flex-wrap gap-3">
            <div>
              <h5 class="mb-1">Predaja testa</h5>
              <p class="text-muted mb-0">
                Odgovoreno je na {{ answeredCount }} od {{ totalQuestions }} pitanja.
              </p>
            </div>

            <button
              class="btn btn-primary px-4"
              @click="submit"
              :disabled="isSubmitting"
            >
              {{ isSubmitting ? 'Predaja u toku...' : 'Predaj test' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>