<script>
import { ref, onMounted } from 'vue'
import { getMyResults } from '@/services/api'
import AppIllustration from '@/components/AppIllustration.vue'

export default {
  components: { AppIllustration },
  setup() {
    const results = ref([])
    const loading = ref(true)

    const loadResults = async () => {
      try {
        const res = await getMyResults()
        results.value = res.data
      } catch (err) {
        console.error(err)
        alert('Učitavanje rezultata nije uspelo.')
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
    <h2 class="page-title mb-4">Moji rezultati</h2>

    <div v-if="loading">Učitavanje...</div>

    <div v-else>
      <div v-if="results.length === 0" class="section-card section-padding text-center text-muted">
        <AppIllustration kind="chart" class="mb-2" />
        <div>Još nemaš rezultata.</div>
      </div>

      <div v-else class="table-container">
      <table class="table table-hover align-middle mb-0">
        <thead>
          <tr>
            <th>Test</th>
            <th>Poeni</th>
            <th>Ukupno</th>
            <th>Status</th>
            <th>Datum</th>
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
                {{ r.score >= r.total * 0.5 ? 'Položeno' : 'Nije položeno' }}
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
</style>