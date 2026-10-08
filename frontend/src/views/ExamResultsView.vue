<script>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { getExamResults, exportExamResults, getExamDetails } from '@/services/api'

export default {
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
        alert('Failed to load results')
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
        link.setAttribute('download', `exam_${route.params.id}_results.xlsx`)
        document.body.appendChild(link)
        link.click()

        link.remove()
        window.URL.revokeObjectURL(url)
      } catch (err) {
        console.error(err)
        alert('Failed to export results')
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
  <div class="container mt-4 mb-5">
    <div class="d-flex justify-content-between align-items-center mb-4">
      <h2 class="page-title mb-0">
        <i class="fa-solid fa-chart-column me-2"></i>
        Results for: {{ exam?.title || 'Exam' }}
      </h2>

      <button
        class="btn btn-success"
        :disabled="exporting || loading"
        @click="handleExport"
      >
        <i class="fa-solid fa-file-excel me-2"></i>
        {{ exporting ? 'Exporting...' : 'Export Excel' }}
      </button>
    </div>

    <div v-if="loading" class="card border-0 shadow-sm">
      <div class="card-body">
        <i class="fa-solid fa-spinner fa-spin me-2"></i>
        Loading...
      </div>
    </div>

    <div v-else>
      <div v-if="results.length === 0" class="alert alert-info">
        <i class="fa-solid fa-circle-info me-2"></i>
        No results yet.
      </div>

      <div v-else class="table-container">
        <table class="table table-hover align-middle mb-0">
          <thead>
            <tr>
              <th><i class="fa-solid fa-user me-1"></i> Student</th>
              <th><i class="fa-solid fa-envelope me-1"></i> Email</th>
              <th><i class="fa-solid fa-star me-1"></i> Score</th>
              <th>Total</th>
              <th><i class="fa-solid fa-triangle-exclamation me-1"></i> Warnings</th>
              <th><i class="fa-solid fa-calendar-days me-1"></i> Date</th>
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
                  {{ r.total > 0 && r.score >= r.total * 0.5 ? 'Passed' : 'Failed' }}
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
.page-title {
  font-size: 2rem;
  font-weight: 800;
  color: var(--app-text);
  border-bottom: 2px solid var(--app-border);
  padding-bottom: 0.75rem;
}

.table-container {
  background: white;
  border-radius: 12px;
  padding: 0.75rem;
  box-shadow: var(--app-shadow);
  overflow: hidden;
}

.table thead {
  background-color: var(--app-bg);
}

.table th {
  font-weight: 600;
  color: var(--app-text);
  border-bottom: 2px solid var(--app-border);
}

.table td {
  padding: 0.9rem 0.75rem;
}

.status-badge {
  width: 110px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  font-size: 0.85rem;
  font-weight: 600;
}

.warning-badge {
  width: 48px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
}
</style>