<template>
  <div class="container py-4">
    <PageHeader title="Testovi" />

    <div v-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-if="loading" class="card border-0 shadow-sm">
      <div class="card-body">Učitavanje...</div>
    </div>

    <div v-else>
      <!-- filter i dugme neposredno iznad liste (ADMIN i nastavnik) -->
      <div v-if="role === 'ADMIN' || role === 'TEACHER'" class="table-toolbar">
        <h5 class="m-0">Svi testovi</h5>
        <div class="d-flex flex-wrap align-items-center gap-2">
          <select v-model="selectedSubject" class="form-select" aria-label="Predmet">
            <option value="">Svi predmeti</option>
            <option v-for="subject in subjects" :key="subject.id" :value="subject.id">
              {{ subject.name }}
            </option>
          </select>
          <router-link to="/exams/create" class="btn btn-primary">
            Napravi test
          </router-link>
        </div>
      </div>

      <div v-if="exams.length === 0" class="section-card empty-state mb-4">
        <AppIllustration kind="clipboard" class="mb-2" />
        <div>Nema dostupnih testova.</div>
      </div>

      <!-- STUDENT VIEW -->
      <template v-if="role === 'STUDENT'">
        <section v-if="pendingExams.length > 0" class="mb-4">
          <h4 class="section-title mb-3">Dostupni testovi</h4>

          <div class="row g-3">
            <div
              class="col-md-6 col-lg-4"
              v-for="exam in pendingExams"
              :key="exam.id"
            >
              <div class="card h-100 border-0 shadow-sm">
                <div class="card-body">
                  <h5 class="card-title mb-2">{{ exam.title }}</h5>

                  <div class="mb-2">
                    <span v-if="exam.exam_mode" class="badge bg-dark me-1">
                      Ispitni režim
                    </span>
                    <span class="badge bg-light text-dark border">
                      {{ exam.subject_name }}
                    </span>
                    <span class="badge bg-light text-dark border ms-1">
                      {{ exam.level }}
                    </span>
                  </div>

                  <div class="small text-muted">
                    <div><strong>Trajanje:</strong> {{ exam.duration_minutes }} min</div>

                    <div v-if="exam.open_at">
                      <strong>Od:</strong> {{ formatDate(exam.open_at) }}
                    </div>

                    <div v-if="exam.close_at">
                      <strong>Do:</strong> {{ formatDate(exam.close_at) }}
                    </div>
                  </div>
                </div>

                <div class="card-footer bg-white border-0">
                  <router-link
                    :to="'/exams/' + exam.id + '/take'"
                    class="btn btn-primary w-100"
                  >
                    Započni test
                  </router-link>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section v-if="completedExams.length > 0">
          <h4 class="section-title mb-3">Završeni testovi</h4>

          <div class="row g-3">
            <div
              class="col-md-6 col-lg-4"
              v-for="exam in completedExams"
              :key="exam.id"
            >
              <div class="card h-100 border-0 shadow-sm">
                <div class="card-body">
                  <div class="d-flex justify-content-between">
                    <h5 class="card-title mb-2">{{ exam.title }}</h5>
                    <span class="badge bg-success status-badge">Završen</span>
                  </div>

                  <div class="mb-2">
                    <span class="badge bg-light text-dark border">
                      {{ exam.subject_name }}
                    </span>
                    <span class="badge bg-light text-dark border ms-1">
                      {{ exam.level }}
                    </span>
                  </div>

                  <div class="small text-muted mb-2">
                    <strong>Poeni:</strong>
                    {{ exam.score }} / {{ exam.total_points }}
                  </div>

                  <span
                    class="badge"
                    :class="isPassed(exam) ? 'bg-success' : 'bg-danger'"
                  >
                    {{ isPassed(exam) ? 'Položeno' : 'Nije položeno' }}
                  </span>
                </div>

                <div class="card-footer bg-white border-0">
                  <router-link to="/my-results" class="btn btn-outline-secondary w-100">
                    Pogledaj rezultat
                  </router-link>
                </div>
              </div>
            </div>
          </div>
        </section>
      </template>

      <!-- ADMIN / TEACHER VIEW -->
      <template v-else>
        <div v-if="exams.length > 0 && filteredExams.length === 0" class="text-muted mb-4">
          Nema testova za izabrani predmet.
        </div>

        <section v-if="publishedExams.length > 0" class="mb-4">
          <h4 class="section-title mb-3">Objavljeni testovi</h4>

          <div class="row g-3">
            <div
              class="col-md-6 col-lg-4"
              v-for="exam in publishedExams"
              :key="exam.id"
            >
              <div class="card h-100 border-0 shadow-sm">
                <div class="card-body">
                  <div class="d-flex justify-content-between">
                    <h5 class="card-title mb-2">{{ exam.title }}</h5>
                    <span class="badge bg-success status-badge">Objavljen</span>
                  </div>

                  <div class="mb-2">
                    <span class="badge bg-light text-dark border">
                      {{ exam.subject_name }}
                    </span>
                    <span class="badge bg-light text-dark border ms-1">
                      {{ exam.level }}
                    </span>
                  </div>

                  <div class="small text-muted">
                    <div><strong>Trajanje:</strong> {{ exam.duration_minutes }} min</div>
                  </div>
                </div>

                <div class="card-footer bg-white border-0 d-flex gap-2">
                  <router-link
                    :to="'/exams/' + exam.id + '/results'"
                    class="btn btn-outline-secondary w-100"
                  >
                    Rezultati
                  </router-link>

                  <button
                    class="btn btn-outline-danger w-100"
                    @click="deleteExamClick(exam)"
                  >
                    Obriši
                  </button>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section v-if="draftExams.length > 0">
          <h4 class="section-title mb-3">Nacrti</h4>

          <div class="row g-3">
            <div
              class="col-md-6 col-lg-4"
              v-for="exam in draftExams"
              :key="exam.id"
            >
              <div class="card h-100 border-0 shadow-sm">
                <div class="card-body">
                  <div class="d-flex justify-content-between">
                    <h5 class="card-title mb-2">{{ exam.title }}</h5>
                    <span class="badge bg-secondary status-badge">Nacrt</span>
                  </div>

                  <div class="mb-2">
                    <span class="badge bg-light text-dark border">
                      {{ exam.subject_name }}
                    </span>
                    <span class="badge bg-light text-dark border ms-1">
                      {{ exam.level }}
                    </span>
                  </div>

                  <div class="small text-muted">
                    <div><strong>Trajanje:</strong> {{ exam.duration_minutes }} min</div>
                  </div>
                </div>

                <div class="card-footer bg-white border-0 d-flex gap-2">
                  <router-link
                    :to="'/exams/' + exam.id"
                    class="btn btn-outline-secondary w-100"
                  >
                    Uredi
                  </router-link>
                  <button
                    class="btn btn-outline-danger w-100"
                    @click="deleteExamClick(exam)"
                  >
                    Obriši
                  </button>

                  <!-- <router-link
                    :to="'/exams/' + exam.id + '/results'"
                    class="btn btn-outline-secondary w-100"
                  >
                    Results
                  </router-link> -->
                </div>
              </div>
            </div>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<script>
import PageHeader from '@/components/PageHeader.vue'
import { getExams, deleteExam, getSubjects } from '@/services/api'
import { formatDbDate } from '@/services/explanationHelpers'
import AppIllustration from '@/components/AppIllustration.vue'

export default {
  components: { PageHeader, AppIllustration },
  data() {
    return {
      exams: [],
      loading: true,
      role: localStorage.getItem('user_role'),
      error: '',
      // filter po predmetu (iz /api/subjects: ADMIN svi, nastavnik samo svoji)
      subjects: [],
      selectedSubject: ''
    }
  },

  computed: {
    filteredExams() {
      if (this.role === 'STUDENT' || !this.selectedSubject) {
        return this.exams
      }

      return this.exams.filter(e => Number(e.subject_id) === Number(this.selectedSubject))
    },

    pendingExams() {
      return this.exams.filter(e => !e.attempt_id)
    },

    completedExams() {
      return this.exams.filter(e => e.attempt_id)
    },

    publishedExams() {
      return this.filteredExams.filter(e => e.is_published)
    },

    draftExams() {
      return this.filteredExams.filter(e => !e.is_published)
    }
  },

  methods: {
    // dd.mm.yyyy. hh:mm, vreme kako je upisano u bazi
    formatDate(dateString) {
      return formatDbDate(dateString)
    },

    isPassed(exam) {
      return exam.total_points > 0 && exam.score >= exam.total_points * 0.5
    },
    async deleteExamClick(exam) {
      if (!confirm(`Da li sigurno želiš da obrišeš test "${exam.title}"?`)) {
        return
      }

      this.error = ''
      try {
        await deleteExam(exam.id)
        this.exams = this.exams.filter(e => e.id !== exam.id)
      } catch (err) {
        console.error(err)
        this.error = err.response?.data?.error || 'Ne mogu da obrišem test.'
      }
    }
  },

  async mounted() {
    if (this.role === 'ADMIN' || this.role === 'TEACHER') {
      getSubjects()
        .then(res => { this.subjects = res.data })
        .catch(() => { this.subjects = [] })
    }
    try {
      const res = await getExams()
      this.exams = res.data
    } catch (err) {
      console.error(err)
      this.error = 'Učitavanje testova nije uspelo.'
    } finally {
      this.loading = false
    }
  }
}
</script>

<style scoped>
</style>