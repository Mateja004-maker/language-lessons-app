<script setup>
import PageHeader from '@/components/PageHeader.vue'
import { onMounted, ref } from 'vue'
import { api } from '@/services/api'

// Administracija predmeta (ADMIN): dodavanje, izmena naziva, brisanje.
// Zamenjuje nekadašnju stranicu Jezici; /admin/languages preusmerava ovde.
const subjects = ref([])
const loading = ref(false)
const error = ref('')
const msg = ref('')

const form = ref({ name: '', code: '' })
const editingId = ref(null)
const editingName = ref('')

// poruka greške na srpskom (backend za predmete već vraća srpske poruke)
function errorText(e, fallback) {
  const status = e?.response?.status
  if (status === 403) return 'Nemaš dozvolu za ovu radnju.'
  return e?.response?.data?.error || fallback
}

async function load() {
  error.value = ''
  loading.value = true
  try {
    const { data } = await api.get('/subjects')
    subjects.value = data
  } catch (e) {
    error.value = errorText(e, 'Učitavanje predmeta nije uspelo.')
  } finally {
    loading.value = false
  }
}

async function addSubject() {
  error.value = ''
  msg.value = ''
  if (!form.value.name.trim() || !form.value.code.trim()) {
    error.value = 'Popuni naziv i oznaku predmeta.'
    return
  }
  try {
    await api.post('/subjects', { name: form.value.name.trim(), code: form.value.code.trim() })
    msg.value = 'Predmet je dodat.'
    form.value = { name: '', code: '' }
    await load()
  } catch (e) {
    error.value = errorText(e, 'Dodavanje predmeta nije uspelo.')
  }
}

function startEdit(subject) {
  editingId.value = subject.id
  editingName.value = subject.name
}

function cancelEdit() {
  editingId.value = null
  editingName.value = ''
}

async function saveName(subject) {
  error.value = ''
  msg.value = ''
  if (!editingName.value.trim()) {
    error.value = 'Naziv predmeta je obavezan.'
    return
  }
  try {
    await api.put(`/subjects/${subject.id}`, { name: editingName.value.trim() })
    msg.value = 'Naziv predmeta je izmenjen.'
    cancelEdit()
    await load()
  } catch (e) {
    error.value = errorText(e, 'Izmena naziva nije uspela.')
  }
}

async function removeSubject(subject) {
  error.value = ''
  msg.value = ''
  if (!confirm(`Da li sigurno želiš da obrišeš predmet "${subject.name}"?`)) return
  try {
    await api.delete(`/subjects/${subject.id}`)
    msg.value = 'Predmet je obrisan.'
    await load()
  } catch (e) {
    error.value = errorText(e, 'Brisanje predmeta nije uspelo.')
  }
}

onMounted(load)
</script>

<template>
  <div class="container py-4">
    <PageHeader title="Predmeti" />

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>

    <div class="row g-3">
      <!-- dodavanje -->
      <div class="col-12">
        <div class="card shadow-sm">
          <div class="card-body">
            <h5 class="card-title mb-3">Novi predmet</h5>
            <div class="row g-2 align-items-end">
              <div class="col-12 col-md-6">
                <label class="form-label">Naziv</label>
                <input v-model="form.name" class="form-control" maxlength="80" placeholder="Npr. Osnove programiranja" />
              </div>
              <div class="col-12 col-md-3">
                <label class="form-label">Oznaka</label>
                <input v-model="form.code" class="form-control" maxlength="10" placeholder="Npr. prog" />
              </div>
              <div class="col-12 col-md-3">
                <button class="btn btn-primary w-100" @click="addSubject">Dodaj predmet</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- tabela -->
      <div class="col-12">
        <div class="card shadow-sm">
          <div class="card-body">
            <div class="table-toolbar">
              <h5 class="card-title m-0">Svi predmeti</h5>
            </div>

            <div v-if="loading" class="text-muted">Učitavanje...</div>

            <div v-else-if="subjects.length === 0" class="text-muted">
              Još nema predmeta.
            </div>

            <div v-else class="table-responsive">
              <table class="table table-sm align-middle">
                <thead class="table-light">
                  <tr>
                    <th>Oznaka</th>
                    <th>Naziv</th>
                    <th class="text-end">Lekcija</th>
                    <th class="text-end">Akcije</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="s in subjects" :key="s.id">
                    <td><span class="badge text-bg-light border">{{ s.code }}</span></td>
                    <td class="fw-semibold">
                      <input
                        v-if="editingId === s.id"
                        v-model="editingName"
                        class="form-control form-control-sm"
                        maxlength="80"
                        aria-label="Naziv predmeta"
                        @keyup.enter="saveName(s)"
                        @keyup.esc="cancelEdit"
                      />
                      <template v-else>{{ s.name }}</template>
                    </td>
                    <td class="text-end">{{ s.lesson_count ?? 0 }}</td>
                    <td class="text-end">
                      <template v-if="editingId === s.id">
                        <button class="btn btn-primary btn-sm me-2" @click="saveName(s)">Sačuvaj</button>
                        <button class="btn btn-outline-secondary btn-sm" @click="cancelEdit">Otkaži</button>
                      </template>
                      <template v-else>
                        <button class="btn btn-outline-secondary btn-sm me-2" @click="startEdit(s)">Izmeni</button>
                        <button class="btn btn-outline-danger btn-sm" @click="removeSubject(s)">Obriši</button>
                      </template>
                    </td>
                  </tr>
                </tbody>
              </table>

              <div class="text-muted small">
                Predmet može da se obriše samo ako ga ne koriste nastavnici, studenti, oblasti,
                lekcije, pitanja, testovi ni referentni skupovi.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
