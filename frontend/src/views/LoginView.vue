<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login } from '@/services/auth'
import AppIllustration from '@/components/AppIllustration.vue'

const router = useRouter()

const email = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function onSubmit() {
  error.value = ''
  loading.value = true
  try {
    await login(email.value, password.value)
    router.push('/')
  } catch (e) {
    error.value = e?.response?.data?.error || 'Prijava nije uspela.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="container py-5">
    <div class="row justify-content-center align-items-center min-vh-100">
      <div class="col-12 col-lg-10">
        <div class="row g-4 align-items-center">

          <div class="col-lg-6 d-none d-lg-block">
            <div class="pe-4">
              <div class="mb-3">
                <AppIllustration kind="test" :size="200" />
              </div>

              <h1 class="fw-bold mb-3" style="font-size: 3rem; line-height: 1.1;">
                Onlajn testiranje, na jednom mestu.
              </h1>

              <p class="text-muted fs-5 mb-4">
                Pristupi testovima i lekcijama iz svojih predmeta
                i prati rezultate i napredak.
              </p>

              <div class="d-flex gap-3 flex-wrap">
                <span class="badge badge-soft px-3 py-2">Testovi</span>
                <span class="badge badge-soft px-3 py-2">Lekcije</span>
                <span class="badge badge-soft px-3 py-2">Rezultati</span>
              </div>
            </div>
          </div>

          <div class="col-12 col-lg-6">
            <div class="card shadow-sm border-0 section-card">
              <div class="card-body p-4 p-md-5">

                <div class="text-center mb-4">
                  <div class="mb-2 icon-card">
                    <i class="fa-solid fa-book-open"></i>
                  </div>

                  <h2 class="fw-bold mb-1">Prijava</h2>

                  <div class="text-muted">
                    Prijavi se da nastaviš
                  </div>
                </div>

                <div class="alert alert-warning py-2 small" role="alert">
                  <i class="fa-solid fa-circle-info me-2"></i>
                  Novi nalozi moraju da budu odobreni od strane administratora.
                </div>

                <div v-if="error" class="alert alert-danger py-2">
                  <i class="fa-solid fa-triangle-exclamation me-2"></i>
                  {{ error }}
                </div>

                <form @submit.prevent="onSubmit">
                  <div class="mb-3">
                    <label class="form-label fw-semibold">
                      <i class="fa-solid fa-envelope me-1"></i>
                      Email
                    </label>

                    <input
                      v-model="email"
                      type="email"
                      class="form-control"
                      placeholder="tvoj@email.com"
                      required
                      autocomplete="username"
                    />
                  </div>

                  <div class="mb-2">
                    <label class="form-label fw-semibold">
                      <i class="fa-solid fa-lock me-1"></i>
                      Lozinka
                    </label>

                    <input
                      v-model="password"
                      type="password"
                      class="form-control"
                      placeholder="Unesi lozinku"
                      required
                      autocomplete="current-password"
                    />
                  </div>

                  <button
                    class="btn btn-primary w-100 mt-4 py-2"
                    type="submit"
                    :disabled="loading"
                  >
                    <span
                      v-if="loading"
                      class="spinner-border spinner-border-sm me-2"
                      role="status"
                    ></span>

                    <i v-else class="fa-solid fa-right-to-bracket me-2"></i>
                    Prijavi se
                  </button>

                  <div class="text-center mt-4">
                    <RouterLink to="/register">
                      <i class="fa-solid fa-user-plus me-1"></i>
                      Nemaš nalog? Registruj se
                    </RouterLink>
                  </div>
                </form>
              </div>
            </div>

            <div class="text-center text-muted small mt-4">
              © {{ new Date().getFullYear() }} Onlajn testiranje
            </div>
          </div>

        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.icon-card {
  font-size: 2.5rem;
  color: var(--app-primary);
}
</style>