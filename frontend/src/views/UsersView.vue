<script setup>
import PageHeader from '@/components/PageHeader.vue'
import { computed, onMounted, ref } from 'vue'
import { api } from '@/services/api'

const subjects = ref([])
const users = ref([])

const email = ref('')
const password = ref('')
const display_name = ref('')
const role = ref('STUDENT')
const selected_subject_ids = ref([])

const error = ref('')
const msg = ref('')
const loading = ref(false)

const editingUserId = ref(null)
const editingSubjectIds = ref([])

const currentRole = localStorage.getItem('user_role')

// filter tabele po ulozi ('' = svi)
const roleFilter = ref('')
const filteredUsers = computed(() =>
  roleFilter.value ? users.value.filter(u => u.role === roleFilter.value) : users.value
)

async function loadSubjects() {
  const { data } = await api.get('/subjects')
  subjects.value = data
}

async function loadUsers() {
  const { data } = await api.get('/users')
  users.value = data
}

async function loadAll() {
  error.value = ''
  loading.value = true
  try {
    await Promise.all([loadSubjects(), loadUsers()])
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam podatke.'
  } finally {
    loading.value = false
  }
}

function subjectName(id) {
  const s = subjects.value.find(s => Number(s.id) === Number(id))
  return s ? s.name : id
}

async function createUser() {
  error.value = ''
  msg.value = ''

  if (!email.value.trim() || !password.value.trim()) {
    error.value = 'Email i lozinka su obavezni.'
    return
  }

  try {
    await api.post('/users', {
      email: email.value.trim(),
      password: password.value.trim(),
      display_name: display_name.value.trim(),
      role: role.value,
      subject_ids: selected_subject_ids.value
    })

    email.value = ''
    password.value = ''
    display_name.value = ''
    role.value = 'STUDENT'
    selected_subject_ids.value = []

    msg.value = 'Korisnik uspešno kreiran.'
    await loadAll()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da kreiram korisnika.'
  }
}

async function deleteUser(user) {
  error.value = ''
  msg.value = ''

  const confirmed = confirm(
    `Da li sigurno želiš da obrišeš korisnika ${user.email}?`
  )
  if (!confirmed) return

  try {
    await api.delete(`/users/${user.id}`)
    msg.value = 'Korisnik je obrisan.'
    await loadUsers()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da obrišem korisnika.'
  }
}
async function approveUser(user) {
  error.value = ''
  msg.value = ''

  try {
    await api.patch(`/users/${user.id}/approve`)
    msg.value = 'Korisnik je odobren.'
    await loadUsers()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da odobrim korisnika.'
  }
}

function startEditSubjects(user) {
  editingUserId.value = user.id
  editingSubjectIds.value = [...(user.subjects || [])]
}

function cancelEditSubjects() {
  editingUserId.value = null
  editingSubjectIds.value = []
}

async function saveSubjects(user) {
  error.value = ''
  msg.value = ''

  try {
    await api.put(`/users/${user.id}/subjects`, {
      subject_ids: editingSubjectIds.value
    })
    msg.value = 'Predmeti su ažurirani.'
    editingUserId.value = null
    await loadUsers()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da izmenim predmete.'
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="container py-4">

    <PageHeader title="Korisnici">
      <select v-model="roleFilter" class="form-select" aria-label="Uloga">
        <option value="">Svi</option>
        <option value="STUDENT">Studenti</option>
        <option value="TEACHER">Nastavnici</option>
        <option value="ADMIN">Administratori</option>
      </select>
    </PageHeader>

    <div v-if="error" class="alert alert-danger">{{ error }}</div>
    <div v-if="msg" class="alert alert-success">{{ msg }}</div>
    <div v-if="loading" class="text-muted">Učitavanje...</div>

    <div class="section-card section-padding mb-4">
      <h5 class="mb-3">Novi korisnik</h5>

      <div class="row g-3">
        <div class="col-md-6">
          <label class="form-label">Ime i prezime</label>
          <input v-model="display_name" class="form-control" />
        </div>

        <div class="col-md-6">
          <label class="form-label">Email</label>
          <input v-model="email" class="form-control" />
        </div>

        <div class="col-md-6">
          <label class="form-label">Lozinka</label>
          <input v-model="password" type="password" class="form-control" />
        </div>

        <div class="col-md-6">
          <label class="form-label">Uloga</label>
          <select v-model="role" class="form-select">
            <option value="STUDENT">Student</option>
            <option value="TEACHER">Nastavnik</option>
          </select>
        </div>

        <div class="col-md-12">
          <label class="form-label">Predmeti (može više odjednom)</label>
          <select v-model="selected_subject_ids" class="form-select" multiple size="4">
            <option v-for="s in subjects" :key="s.id" :value="s.id">
              {{ s.name }}
            </option>
          </select>
          <small class="text-muted">Drži Ctrl (ili Cmd) da izabereš više predmeta.</small>
        </div>
      </div>

      <div class="mt-4 text-end">
        <button class="btn btn-primary px-4" @click="createUser">
          Napravi korisnika
        </button>
      </div>
    </div>

    <div class="section-card section-padding">
      <div class="d-flex justify-content-between align-items-center mb-3">
        <h5 class="m-0">Svi korisnici</h5>
        <button class="btn btn-outline-secondary btn-sm" @click="loadUsers">
          Osveži
        </button>
      </div>

      <div class="table-responsive">
        <table class="table table-hover align-middle">
          <thead class="table-light">
            <tr>
              <th>ID</th>
              <th>Ime</th>
              <th>Email</th>
              <th>Uloga</th>
              <th>Predmeti</th>
              <th>Status</th>
              <th class="text-end">Akcije</th>
            </tr>
          </thead>

          <tbody>
            <template v-for="u in filteredUsers" :key="u.id">
              <tr>
                <td>{{ u.id }}</td>
                <td>{{ u.display_name || '-' }}</td>
                <td>{{ u.email }}</td>
                <td>
                  <span v-if="u.role === 'ADMIN'" class="badge badge-soft">Administrator</span>
                  <span v-else-if="u.role === 'TEACHER'" class="badge badge-soft">Nastavnik</span>
                  <span v-else class="badge badge-soft">Student</span>
                </td>
                <td>
                  <span
                    v-for="sid in (u.subjects || [])"
                    :key="sid"
                    class="badge text-bg-light border me-1"
                  >
                    {{ subjectName(sid) }}
                  </span>
                  <span v-if="!(u.subjects || []).length" class="text-muted">-</span>
                </td>
                <td>
                  <span v-if="u.is_active == 1" class="badge text-bg-success">
                    Odobren
                  </span>

                  <span v-else class="badge text-bg-secondary">
                    Na čekanju
                  </span>
                </td>
                <td class="text-end">
                  <div class="d-flex justify-content-end gap-2">
                    <button
                      v-if="u.is_active != 1 && u.role !== 'ADMIN'"
                      class="btn btn-outline-secondary btn-sm"
                      @click="approveUser(u)"
                    >
                      Odobri
                    </button>

                    <button
                      v-if="u.role !== 'ADMIN'"
                      class="btn btn-outline-secondary btn-sm"
                      @click="startEditSubjects(u)"
                    >
                      Izmeni predmete
                    </button>

                    <button
                      v-if="u.role !== 'ADMIN'"
                      class="btn btn-outline-danger btn-sm"
                      @click="deleteUser(u)"
                    >
                      Obriši
                    </button>

                    <span v-if="u.role === 'ADMIN'" class="text-muted small">
                      Zaštićen
                    </span>
                  </div>
                </td>
              </tr>

              <tr v-if="editingUserId === u.id">
                <td colspan="7">
                  <div class="d-flex align-items-start gap-3 flex-wrap">
                    <select v-model="editingSubjectIds" class="form-select" multiple size="4" style="max-width: 300px;">
                      <option v-for="s in subjects" :key="s.id" :value="s.id">
                        {{ s.name }}
                      </option>
                    </select>
                    <div class="d-flex flex-column gap-2">
                      <button class="btn btn-primary btn-sm" @click="saveSubjects(u)">Sačuvaj</button>
                      <button class="btn btn-outline-secondary btn-sm" @click="cancelEditSubjects">Otkaži</button>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

  </div>
</template>

<style scoped>
</style>
