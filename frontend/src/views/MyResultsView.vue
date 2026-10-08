<script>
import { ref, onMounted } from 'vue'
import { getMyResults } from '@/services/api'

export default {
  setup() {
    const results = ref([])
    const loading = ref(true)

    const loadResults = async () => {
      try {
        const res = await getMyResults()
        results.value = res.data
      } catch (err) {
        console.error(err)
        alert('Failed to load results')
      } finally {
        loading.value = false
      }
    }

    onMounted(loadResults)

    return { results, loading }
  }
}
</script>

<template>
  <div class="container mt-4">
    <h2 class="page-title mb-4">My Results</h2>

    <div v-if="loading">Loading...</div>

    <div v-else>
      <div v-if="results.length === 0" class="alert alert-info">
        No results yet.
      </div>

      <div v-else class="table-container">
      <table class="table table-hover align-middle mb-0">
        <thead>
          <tr>
            <th>Exam</th>
            <th>Score</th>
            <th>Total</th>
            <th>Status</th>
            <th>Date</th>
            <th></th>
          </tr>
        </thead>

        <tbody>
          <tr v-for="r in results" :key="r.id">
            <td>{{ r.title }}</td>
            <td class="fw-semibold">{{ r.score }}</td>
            <td class="text-muted">{{ r.total }}</td>

            <td>
              <span
                class="badge status-badge"
                :class="r.score >= r.total * 0.5 ? 'bg-success' : 'bg-danger'"
              >
                {{ r.score >= r.total * 0.5 ? 'Passed' : 'Failed' }}
              </span>
            </td>

            <td>{{ new Date(r.submitted_at).toLocaleString() }}</td>

            <td class="text-end">
              <router-link :to="`/my-results/${r.id}`" class="btn btn-outline-primary btn-sm">
                Detalji
              </router-link>
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
  font-size: 2.4rem;
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

.page-title {
  font-size: 2rem;
  font-weight: 800;
  color: var(--app-text);
  border-bottom: 2px solid var(--app-border);
  padding-bottom: 0.75rem;
}
</style>