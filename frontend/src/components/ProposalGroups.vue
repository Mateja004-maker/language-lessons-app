<script setup>
import { computed, ref } from 'vue'

// Grupisanje AI predloga po originalnom (izvornom) pitanju.
// Slepo ocenjivanje: redosled se NE menja - grupe idu redom prvog pojavljivanja
// u (nasumicnoj) listi sa servera, a predlozi u grupi ostaju u istom redosledu.
// Nista u grupi ne otkriva model.
const props = defineProps({
  items: { type: Array, required: true },
  // da li je trenutni korisnik vec ocenio predlog (za broj neocenjenih)
  isRated: { type: Function, default: item => Boolean(item.rated_by_me) }
})

const PREVIEW_LENGTH = 140

const groups = computed(() => {
  const byKey = new Map()
  for (const item of props.items) {
    const key = item.source_question_id ?? 'bez-izvora'
    if (!byKey.has(key)) {
      byKey.set(key, { key, sourceText: item.source_question_text || '', items: [], unrated: 0 })
    }
    const group = byKey.get(key)
    group.items.push(item)
    if (!props.isRated(item)) group.unrated += 1
  }
  return [...byKey.values()]
})

// grupe su podrazumevano otvorene (predlozi vidljivi kao ranije); pamti se samo sta je zatvoreno
const closed = ref(new Set())
function toggle(key) {
  const next = new Set(closed.value)
  next.has(key) ? next.delete(key) : next.add(key)
  closed.value = next
}

function preview(text) {
  if (!text) return 'Originalno pitanje nije dostupno'
  return text.length > PREVIEW_LENGTH ? text.slice(0, PREVIEW_LENGTH).trimEnd() + '…' : text
}

// 1, 21, 31... predlog; ostalo predloga
function proposalsLabel(n) {
  return n % 10 === 1 && n % 100 !== 11 ? `${n} predlog` : `${n} predloga`
}

// 1 neocenjen, 2-4 neocenjena, 0 i 5+ neocenjenih (11-14 neocenjenih)
function unratedLabel(n) {
  const last = n % 10
  const lastTwo = n % 100
  if (last === 1 && lastTwo !== 11) return `${n} neocenjen`
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${n} neocenjena`
  return `${n} neocenjenih`
}
</script>

<template>
  <div v-for="group in groups" :key="group.key" class="proposal-group mb-3">
    <button
      type="button"
      class="group-header"
      :aria-expanded="!closed.has(group.key)"
      :title="group.sourceText"
      @click="toggle(group.key)"
    >
      <i
        class="fa-solid me-2 group-chevron"
        :class="closed.has(group.key) ? 'fa-chevron-right' : 'fa-chevron-down'"
        aria-hidden="true"
      ></i>
      <span class="group-label">Originalno pitanje:</span>
      <span class="group-text">{{ preview(group.sourceText) }}</span>
      <span class="group-counts">
        <span class="badge text-bg-light border">{{ proposalsLabel(group.items.length) }}</span>
        <span class="badge text-bg-light border">{{ unratedLabel(group.unrated) }}</span>
      </span>
    </button>

    <div v-if="!closed.has(group.key)" class="group-body">
      <slot v-for="item in group.items" :key="item.id" name="item" :item="item" />
    </div>
  </div>
</template>

<style scoped>
.group-header {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.25rem 0.5rem;
  width: 100%;
  text-align: left;
  padding: 0.85rem 1rem;
  border: none;
  border-radius: var(--app-radius);
  background: var(--app-surface);
  box-shadow: var(--app-shadow);
  color: var(--app-text);
}

.group-header:hover {
  box-shadow: var(--app-shadow-hover);
}

.group-chevron {
  color: var(--app-icon);
  width: 1rem;
}

.group-label {
  color: var(--app-text-muted);
  font-size: 0.9rem;
}

.group-text {
  font-weight: 600;
  flex: 1 1 20rem;
  min-width: 0;
}

.group-counts {
  display: flex;
  gap: 0.4rem;
  margin-left: auto;
}

.group-body {
  margin-top: 0.75rem;
  margin-left: 1rem;
  padding-left: 1rem;
  border-left: 2px solid var(--app-border);
}
</style>
