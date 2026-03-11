<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { login } from '@/services/auth'

const router = useRouter()
const email = ref('')
const password = ref('')
const error = ref('')

async function onSubmit() {
  error.value = ''
  try {
    await login(email.value, password.value)
    router.push('/')
  } catch (e) {
    error.value = e?.response?.data?.error || 'Login failed'
  }
}
</script>
<template>
  <div style="max-width:420px;margin:40px auto;">
    <h2>Login</h2>

    <form @submit.prevent="onSubmit">
      <div>
        <label>Email</label>
        <input v-model="email" type="email" required />
      </div>

      <div style="margin-top:10px;">
        <label>Password</label>
        <input v-model="password" type="password" required />
      </div>

      <button style="margin-top:14px;" type="submit">Sign in</button>
      <p v-if="error" style="color:#b00020;">{{ error }}</p>
    </form>

    <p style="margin-top:14px;color:#555;">
      Test nalozi: admin@test.com / Admin123!
    </p>
  </div>
  
</template>
<style scoped>
/* wrapper */
div {
  color: #fff;
}

/* forma */
label {
  display: block;
  margin-top: 10px;
  color: #fff;
}

input {
  width: 100%;
  padding: 10px;
  margin-top: 6px;
  border-radius: 8px;
  border: 1px solid #444;
  background: #fff;
  color: #111;
}

button {
  padding: 10px 14px;
  border-radius: 8px;
  border: 0;
  cursor: pointer;
}
</style>

