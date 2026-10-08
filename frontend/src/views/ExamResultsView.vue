<script>
import PageHeader from '@/components/PageHeader.vue'
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getExamResults, exportExamResults, getExamDetails } from '@/services/api'

export default {
  components: { PageHeader },
  setup() {
    const route = useRoute()
    const results = ref([])
    const loading = ref(true)
    const exporting = ref(false)
    const exam = ref(null)

    const loadResults = async () => {
      try {
        const examRes = await getExamDetails(route.params.id)
        exam.value = examRes.data

        const res = await getExamResults(route.params.id)
        results.value = res.data
      } catch (err) {
        console.error(err)
        alert('Učitavanje rezultata nije uspelo.')
      } finally {
        loading.value = false
      }
    }

    const handleExport = async () => {
      try {
        exporting.value = true
        const res = await exportExamResults(route.params.id)

        const url = window.URL.createObjectURL(new Blob([res.data]))
        const link = document.createElement('a')

        link.href = url
        link.setAttribute('download', `test_${route.params.id}_rezultati.xlsx`)
        document.body.appendChild(link)
        link.click()

        link.remove()
        window.URL.revokeObjectURL(url)
      } catch (err) {
        console.error(err)
        alert('Izvoz rezultata nije uspeo.')
      } finally {
        exporting.value = false
      }
    }

    onMounted(loadResults)

    return {
      results,
      loading,
      exporting,
      handleExport,
      exam
    }
  }
}
</script>

<template>
  <div class="container py-4">
    <PageHeader :title="`Rezultati: ${exam?.title || 'Test'}`">
      <button
        class="btn btn-primary"
        :disabled="exporting || loading"
        @click="handleExport"
      >
        <i class="fa-solid fa-file-excel me-2"></i>
        {{ exporting ? 'Izvoz u toku...' : 'Izvezi u Excel' }}
      </button>
    </PageHeader>

    <div v-if="loading" class="card border-0 shadow-sm">
      <div class="card-body">
        <i class="fa-solid fa-spinner fa-spin me-2"></i>
        Učitavanje...
      </div>
    </div>

    <div v-else>
      <div v-if="results.length === 0" class="alert alert-info">
        <i class="fa-solid fa-circle-info me-2"></i>
        Još nema rezultata.
      </div>

      <div v-else class="table-container">
        <table class="table table-hover align-middle mb-0">
          <thead>
            <tr>
              <th><i class="fa-solid fa-user me-1"></i> Student</th>
              <th><i class="fa-solid fa-envelope me-1"></i> Email</th>
              <th><i class="fa-solid fa-star me-1"></i> Poeni</th>
              <th>Ukupno</th>
              <th><i class="fa-solid fa-triangle-exclamation me-1"></i> Upozorenja</th>
              <th><i class="fa-solid fa-calendar-days me-1"></i> Datum</th>
              <th>Status</th>
            </tr>
          </thead>

          <tbody>
            <tr v-for="r in results" :key="r.id">
              <td class="fw-semibold">{{ r.display_name }}</td>
              <td>{{ r.email }}</td>
              <td class="fw-semibold">{{ r.score }}</td>
              <td class="text-muted">{{ r.total }}</td>

              <td>
                <span
                  class="badge warning-badge"
                  :class="r.tab_warnings >= 3 ? 'bg-danger' : r.tab_warnings > 0 ? 'bg-warning text-dark' : 'bg-success'"
                >
                  {{ r.tab_warnings || 0 }}
                </span>
              </td>

              <td>{{ new Date(r.submitted_at).toLocaleString() }}</td>

              <td>
                <span
                  class="badge status-badge"
                  :class="r.total > 0 && r.score >= r.total * 0.5 ? 'bg-success' : 'bg-danger'"
                >
                  <i
                    class="me-1"
                    :class="r.total > 0 && r.score >= r.total * 0.5 ? 'fa-solid fa-check' : 'fa-solid fa-xmark'"
                  ></i>
                  {{ r.total > 0 && r.score >= r.total * 0.5 ? 'Položeno' : 'Nije položeno' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<style scoped>
</style>