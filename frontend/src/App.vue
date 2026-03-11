<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppNavbar from '@/components/AppNavbar.vue'

const route = useRoute()
const showNavbar = computed(() => route.name !== 'login')
</script>

<template>
  <AppNavbar v-if="showNavbar" />
  <router-view />
</template>