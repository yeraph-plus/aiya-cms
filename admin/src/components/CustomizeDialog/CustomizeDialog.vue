<script setup>
import {
  Checkmark48Filled as CheckIcon,
  WeatherMoon48Regular as MoonIcon,
  WeatherSunny48Regular as SunIcon,
} from '@vicons/fluent'
import { storeToRefs } from 'pinia'
import useColors from '~/composables/useColors'

const { t } = useI18n()
const layout = useLayoutStore()
const { isRtl, isFluid } = storeToRefs(layout)
function setLight() {
  if (layout.isDark) layout.toggleTheme()
}

function setDark() {
  if (!layout.isDark) layout.toggleTheme()
}

const colors = useColors().primaryColors
const selectedColorIndex = computed(() => colors.indexOf(layout.themeColor))
function setColor(index) {
  const color = colors[index]
  if (color) layout.setThemeColor(color)
}
</script>

<template>
  <div class="section">
    <NTag type="primary" :bordered="false" size="small" class="mb-3 font-bold">
      {{ t('customize.theme') }}
    </NTag>

    <n-space justify="start" size="large">
      <NButton ghost class="p-7" :type="layout.isDark === false ? 'primary' : 'default'" size="large" @click="setLight">
        <template #icon>
          <NIcon>
            <SunIcon />
          </NIcon>
        </template>
      </NButton>

      <NButton ghost class="w-full p-7" :type="layout.isDark ? 'primary' : 'default'" size="large" @click="setDark">
        <template #icon>
          <NIcon>
            <MoonIcon />
          </NIcon>
        </template>
      </NButton>
    </n-space>
  </div>
  <div class="section">
    <NTag type="primary" :bordered="false" size="small" class="mb-3 font-bold">
      {{ t('customize.color') }}
    </NTag>

    <div>
      <NButton v-for="(color, index) of colors" :key="color" :data-theme-color="color" :color="color" size="medium" circle icon="CheckIcon"
        class="mx-1" @click="setColor(index)">
        <template #icon>
          <CheckIcon v-if="selectedColorIndex === index" />
          <span v-else />
        </template>
      </NButton>
    </div>
  </div>
  <div class="section">
    <NTag type="primary" :bordered="false" size="small" class="mb-3 font-bold">
      {{ t('customize.layout') }}
    </NTag>

    <div py-3>
      <n-switch v-model:value="isFluid" />
      {{ t('customize.fluid') }}
    </div>
    <div py-3>
      <n-switch v-model:value="isRtl" />
      {{ t('customize.rtl') }}

    </div>
  </div>
</template>

<style lang="scss" scoped>
.section {
    padding: .8rem 0;
    .section-title {
        font-weight: 500;
        padding: 0.2rem 0;
        border-bottom: solid 1px #CCC;
        margin-bottom:1rem;
    }
}

</style>
