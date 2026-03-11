<script setup>
import { onMounted, ref } from 'vue'
import { api } from '@/services/api'

const languages = ref([])
const code = ref('')
const name = ref('')
const error = ref('')
const msg = ref('')
const loading = ref(false)

// --- modal state ---
const showModal = ref(false)
const pendingLanguage = ref(null) // {id, code, name, lessons_count?}
const pendingCount = ref(0)
const modalLoading = ref(false)

async function load() {
  error.value = ''
  try {
    loading.value = true
    const { data } = await api.get('/languages')
    languages.value = data
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne mogu da učitam jezike'
  } finally {
    loading.value = false
  }
}

async function addLanguage() {
  error.value = ''
  msg.value = ''

  if (!code.value.trim() || !name.value.trim()) {
    error.value = 'Popuni code i name.'
    return
  }

  try {
    await api.post('/languages', { code: code.value.trim(), name: name.value.trim() })
    code.value = ''
    name.value = ''
    msg.value = 'Dodato!'
    await load()
  } catch (e) {
    error.value = e?.response?.data?.error || 'Ne može da doda jezik'
  }
}

/**
 * VARIJANTA A (preporučeno): backend vrati lessons_count uz /languages
 * - onda će l.lessons_count postojati i modal radi bez dodatnih poziva
 *
 * VARIJANTA B: ako nema lessons_count, pozovi endpoint za count (vidi dole u kodu)
 */
async function getLessonsCountForLanguage(languageId, langFromList) {
  // Ako backend već šalje count u listi jezika:
  if (langFromList && typeof langFromList.lessons_count === 'number') {
    return langFromList.lessons_count
  }

  // Ako nema, pokušaj posebnog endpoint-a:
  // (ti možeš dodati backend rutu: GET /languages/<id>/lessons-count)
  const { data } = await api.get(`/languages/${languageId}/lessons-count`)
  // očekujemo: { count: 3 }
  return data?.count ?? 0
}

async function openDeleteModal(lang) {
  error.value = ''
  msg.value = ''
  pendingLanguage.value = lang
  pendingCount.value = 0
  showModal.value = true

  modalLoading.value = true
  try {
    pendingCount.value = await getLessonsCountForLanguage(lang.id, lang)
  } catch (e) {
    // Ako count endpoint ne postoji, makar pokaži “nepoznato”
    pendingCount.value = -1
  } finally {
    modalLoading.value = false
  }
}

function closeModal() {
  showModal.value = false
  pendingLanguage.value = null
  pendingCount.value = 0
  modalLoading.value = false
}

async function confirmDelete() {
  if (!pendingLanguage.value) return

  error.value = ''
  msg.value = ''
  try {
    // Ovde trenutno brišemo.
    // Ako radiš SOFT DELETE (Opcija C), samo promeni ovu liniju na tvoj endpoint (npr. PUT/PATCH).
    await api.delete(`/languages/${pendingLanguage.value.id}`)

    msg.value = 'Obrisano.'
    closeModal()
    await load()
  } catch (e) {
    error.value =
      e?.response?.data?.error || 'Ne može da obriše jezik (možda ima lekcije)'
    closeModal()
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <h2>Admin: Languages</h2>

    <div class="form">
      <div>
        <label>Code</label>
        <input v-model="code" placeholder="en" />
      </div>

      <div>
        <label>Name</label>
        <input v-model="name" placeholder="English" />
      </div>

      <button class="btn" @click="addLanguage">Add</button>
    </div>

    <p v-if="msg" class="msg">{{ msg }}</p>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="loading">Učitavam...</p>

    <ul v-if="!loading" class="list">
      <li v-for="l in languages" :key="l.id" class="item">
        <span>{{ l.id }} — {{ l.code }} — {{ l.name }}</span>

        <button class="danger" @click="openDeleteModal(l)">
          Delete
        </button>
      </li>
    </ul>

    <!-- MODAL -->
    <div v-if="showModal" class="backdrop" @click.self="closeModal">
      <div class="modal">
        <h3>Potvrda brisanja</h3>

        <p v-if="pendingLanguage">
          Jezik: <b>{{ pendingLanguage.code }}</b> — {{ pendingLanguage.name }}
        </p>

        <p v-if="modalLoading">Učitavam broj lekcija...</p>

        <p v-else>
          <template v-if="pendingCount >= 0">
            Jezik ima <b>{{ pendingCount }}</b> lekcija. Sigurno hoćeš da obrišeš?
          </template>
          <template v-else>
            Ne mogu da izračunam broj lekcija (endpoint ne postoji). Sigurno hoćeš da obrišeš?
          </template>
        </p>

        <div class="actions">
          <button class="btn" @click="closeModal">Cancel</button>
          <button class="danger" @click="confirmDelete">Da, obriši</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page {
  max-width: 900px;
  margin: 30px auto;
  padding: 16px;
  color: #fff;
}

.form {
  display: flex;
  gap: 10px;
  align-items: end;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

label {
  display: block;
  margin-bottom: 6px;
}

input {
  padding: 10px;
  border-radius: 8px;
  border: 1px solid #444;
  background: #fff;
  color: #111;
  min-width: 220px;
}

.btn {
  padding: 10px 14px;
  border-radius: 8px;
  border: 0;
  cursor: pointer;
}

.msg { color: #2ecc71; }
.error { color: #ff6b6b; }

.list {
  margin-top: 12px;
  padding-left: 0;
  list-style: none;
}

.item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  margin-bottom: 10px;
  background: rgba(255, 255, 255, 0.04);
}

.danger {
  padding: 8px 10px;
  border-radius: 8px;
  border: 0;
  cursor: pointer;
  background: #ff4d4f;
  color: #fff;
}

/* modal */
.backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 18px;
}

.modal {
  width: 100%;
  max-width: 520px;
  background: #161616;
  border: 1px solid #2a2a2a;
  border-radius: 12px;
  padding: 16px;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 14px;
}
</style>