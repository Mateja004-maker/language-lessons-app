<script setup>
// Jednostavne SVG ilustracije (sive i tamnoplave, najviše jedan detalj u akcentu) (sopstveni crteži, deo projekta - bez spoljnih izvora i licenci).
// Boje dolaze iz teme (src/assets/theme.css), pa prate promenu palete.
defineProps({
  // test | register | inbox | scale | book | star | chart | clipboard
  kind: { type: String, required: true },
  size: { type: Number, default: 160 }
})
</script>

<template>
  <svg
    class="app-illustration"
    :width="size"
    :height="size * 0.75"
    viewBox="0 0 160 120"
    role="img"
    aria-hidden="true"
    focusable="false"
  >
    <ellipse class="soft" cx="80" cy="108" rx="58" ry="7" />
    <circle class="soft" cx="80" cy="56" r="46" />

    <!-- prijava: list testa sa kvačicom -->
    <g v-if="kind === 'test'">
      <rect class="surface line" x="50" y="22" width="60" height="76" rx="8" />
      <rect class="accent" x="66" y="16" width="28" height="12" rx="4" />
      <rect class="border" x="60" y="42" width="40" height="5" rx="2.5" />
      <rect class="border" x="60" y="54" width="30" height="5" rx="2.5" />
      <circle class="hot" cx="96" cy="84" r="16" />
      <path class="tick" d="M88 84 l6 6 l10 -12" />
    </g>

    <!-- registracija: korisnik sa znakom + -->
    <g v-else-if="kind === 'register'">
      <circle class="primary" cx="74" cy="42" r="16" />
      <path class="primary" d="M44 96 c0 -22 14 -34 30 -34 s30 12 30 34 z" />
      <circle class="hot" cx="108" cy="78" r="15" />
      <path class="plus" d="M108 71 v14 M101 78 h14" />
    </g>

    <!-- nema predloga: prazna fioka -->
    <g v-else-if="kind === 'inbox'">
      <path class="surface line" d="M42 62 l12 -28 h52 l12 28 v26 a6 6 0 0 1 -6 6 h-64 a6 6 0 0 1 -6 -6 z" />
      <path class="line" d="M42 62 h24 l6 10 h16 l6 -10 h24" fill="none" />
      <circle class="hot" cx="80" cy="22" r="5" />
    </g>

    <!-- druga ocena: vaga -->
    <g v-else-if="kind === 'scale'">
      <rect class="primary" x="77" y="28" width="6" height="62" rx="3" />
      <rect class="primary" x="60" y="88" width="40" height="7" rx="3.5" />
      <rect class="primary" x="44" y="34" width="72" height="5" rx="2.5" />
      <path class="line" d="M50 39 l-10 26 M50 39 l10 26 M110 39 l-10 26 M110 39 l10 26" fill="none" />
      <path class="accent" d="M38 65 h24 a12 9 0 0 1 -24 0 z" />
      <path class="surface line" d="M98 65 h24 a12 9 0 0 1 -24 0 z" />
      <circle class="hot" cx="80" cy="26" r="6" />
    </g>

    <!-- nema lekcija: otvorena knjiga -->
    <g v-else-if="kind === 'book'">
      <path class="surface line" d="M80 40 c-10 -8 -26 -10 -38 -6 v52 c12 -4 28 -2 38 6 z" />
      <path class="surface line" d="M80 40 c10 -8 26 -10 38 -6 v52 c-12 -4 -28 -2 -38 6 z" />
      <path class="line" d="M50 50 c8 -2 16 -1 22 2 M50 62 c8 -2 16 -1 22 2 M88 52 c6 -3 14 -4 22 -2" fill="none" />
      <rect class="hot" x="96" y="30" width="8" height="22" rx="1" />
    </g>

    <!-- nema omiljenih: zvezdica -->
    <g v-else-if="kind === 'star'">
      <path class="accent" d="M80 22 l11 23 l25 3 l-18 17 l5 25 l-23 -12 l-23 12 l5 -25 l-18 -17 l25 -3 z" />
      <circle class="hot" cx="118" cy="30" r="4" />
      <circle class="gray" cx="44" cy="38" r="3" />
    </g>

    <!-- nema rezultata: grafikon -->
    <g v-else-if="kind === 'chart'">
      <rect class="surface line" x="40" y="26" width="80" height="66" rx="8" />
      <rect class="primary" x="54" y="60" width="12" height="22" rx="2" />
      <rect class="accent" x="74" y="48" width="12" height="34" rx="2" />
      <rect class="gray" x="94" y="38" width="12" height="44" rx="2" />
    </g>

    <!-- nema testova: prazan list sa isprekidanim redovima -->
    <g v-else-if="kind === 'clipboard'">
      <rect class="surface line" x="50" y="22" width="60" height="76" rx="8" />
      <rect class="hot" x="66" y="16" width="28" height="12" rx="4" />
      <path class="dash" d="M60 46 h40 M60 60 h40 M60 74 h26" />
    </g>
  </svg>
</template>

<style scoped>
.app-illustration {
  display: inline-block;
  max-width: 100%;
  height: auto;
}

/* sive i tamnoplave; najviše jedan detalj u akcentu (.hot) po ilustraciji */
.soft { fill: var(--app-neutral-soft); }
.surface { fill: var(--app-surface); }
/* samo plave i sive nijanse iz teme */
.primary { fill: var(--app-primary); }
.accent { fill: var(--app-navbar); }
.gray { fill: var(--app-neutral); }
.hot { fill: var(--app-accent); }
.border { fill: var(--app-border); }

.line {
  stroke: var(--app-navbar);
  stroke-width: 3;
  stroke-linejoin: round;
  stroke-linecap: round;
}

.tick,
.plus {
  fill: none;
  stroke: var(--app-surface);
  stroke-width: 4;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.dash {
  fill: none;
  stroke: var(--app-border);
  stroke-width: 5;
  stroke-linecap: round;
  stroke-dasharray: 8 6;
}
</style>
