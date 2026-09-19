<template>
  <section class="d-flex flex-column ga-3">
    <v-divider />
    <h3 class="text-subtitle-1">{{ t('人工群管理', 'Manual moderation') }}</h3>
    <v-select v-model="group" :items="groups" item-title="name" item-value="id" :label="t('目标群', 'Group')" variant="outlined" density="compact" />
    <v-select v-model="action" :items="actions" :label="t('操作', 'Action')" variant="outlined" density="compact" />
    <v-text-field v-if="action === 'mute' || action === 'unmute'" v-model="member" :label="t('成员业务 ID', 'Member business ID')" variant="outlined" density="compact" />
    <v-textarea v-if="action === 'announce'" v-model="text" :label="t('公告内容', 'Announcement')" :maxlength="2000" counter variant="outlined" rows="3" />
    <v-btn class="align-self-start" prepend-icon="mdi-eye" variant="tonal" :loading="busy" :disabled="!group" @click="preview">{{ t('预览操作', 'Preview') }}</v-btn>
    <v-alert v-if="error" type="error" variant="tonal">{{ error }}</v-alert>
    <v-alert v-if="result" :type="result === 'verified' ? 'success' : 'warning'" variant="tonal">{{ statuses[result] || result }}</v-alert>
    <v-dialog v-model="dialog" max-width="560" :persistent="busy">
      <v-card>
        <v-card-title class="text-h3 pa-4 pb-0 pl-6">{{ t('确认群管理操作', 'Confirm moderation') }}</v-card-title>
        <v-card-text v-if="pending" class="text-body-2" style="overflow-wrap: anywhere">
          <p>{{ t('机器人', 'Bot') }}: {{ instance }}</p>
          <p>{{ t('账号', 'Account') }}: {{ pending.account }}</p>
          <p>{{ t('目标群', 'Group') }}: {{ groups.find(g => String(g.id) === String(pending?.group))?.name }} ({{ pending.group }})</p>
          <p>{{ t('操作', 'Action') }}: {{ actions.find(a => a.value === pending?.action)?.title }}</p>
          <p v-if="pending.member">{{ t('成员', 'Member') }}: {{ pending.member }}</p>
          <p v-if="pending.text" style="white-space: pre-wrap">{{ pending.text }}</p>
          <p>{{ t('影响', 'Impact') }}: {{ pending.action === 'mute_all' ? t('全群普通成员将无法发言，不会自动解除。', 'All ordinary members will be muted until explicitly restored.') : pending.action === 'mute' ? t('指定成员禁言一分钟。', 'The member will be muted for one minute.') : t('立即修改所选群的状态或发布公告。', 'Immediately updates the selected group or publishes the announcement.') }}</p>
          <p>{{ t('确认有效期至', 'Expires at') }}: {{ new Date(pending.expires * 1000).toLocaleTimeString() }}</p>
        </v-card-text>
        <v-card-actions><v-spacer /><v-btn variant="text" :disabled="busy" @click="dialog = false">{{ t('取消', 'Cancel') }}</v-btn><v-btn variant="tonal" color="warning" :loading="busy" @click="confirm">{{ t('确认执行一次', 'Execute once') }}</v-btn></v-card-actions>
      </v-card>
    </v-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { botApi } from '@/api/v1';
import { useI18n } from '@/i18n/composables';
const props = defineProps<{ instance: string; groups: Array<{ id: string; name: string }> }>();
const { locale } = useI18n();
const t = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en;
const group = ref(''), member = ref(''), action = ref('mute'), text = ref('');
const busy = ref(false), dialog = ref(false), error = ref(''), result = ref('');
const pending = ref<Record<string, any> | null>(null);
const actions = computed(() => [
  { title: t('成员禁言一分钟', 'Mute member for one minute'), value: 'mute' },
  { title: t('成员解禁', 'Unmute member'), value: 'unmute' },
  { title: t('发布公告', 'Publish announcement'), value: 'announce' },
  { title: t('开启全员禁言', 'Mute all members'), value: 'mute_all' },
  { title: t('解除全员禁言', 'Unmute all members'), value: 'unmute_all' },
]);
const statuses = computed<Record<string, string>>(() => ({ verified: t('已回读确认', 'Verified by readback'), accepted: t('服务端已接受，实际状态尚未回读确认', 'Accepted; resulting state has not been verified'), unknown: t('结果未知，请先核对平台状态，不要重复操作', 'Unknown outcome. Check platform state before another operation') }));
watch(() => props.instance, () => { pending.value = null; dialog.value = false; result.value = ''; error.value = ''; group.value = ''; });
async function call(fields: Record<string, any>) {
  const response = await botApi.registration('wangshangliao', { ...fields, action: fields.action, instance_id: props.instance });
  const data = response.data;
  if (data.status !== 'ok') throw new Error(data.message || 'Request failed');
  return data.data;
}
async function preview() {
  busy.value = true; error.value = ''; result.value = '';
  try { pending.value = await call({ action: 'moderation_preview', operation_action: action.value, group: Number(group.value), member: Number(member.value), text: text.value }); dialog.value = true; }
  catch (e: any) { error.value = e.message; }
  finally { busy.value = false; }
}
async function confirm() {
  if (!pending.value) return;
  busy.value = true; error.value = '';
  const token = pending.value.approval_token;
  pending.value = null;
  try { const data = await call({ action: 'moderation_execute', approval_token: token }); result.value = data.status; }
  catch (e: any) { error.value = t('确认已消耗，请核对操作结果：', 'Confirmation consumed. Check the result: ') + e.message; }
  finally { busy.value = false; dialog.value = false; }
}
</script>
