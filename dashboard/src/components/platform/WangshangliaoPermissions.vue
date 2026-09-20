<template>
  <section class="d-flex flex-column ga-3">
    <v-divider />
    <h3 class="text-subtitle-1">{{ t('自动回复', 'Automatic replies') }}</h3>
    <v-switch :model-value="modelValue.reply_private !== false" @update:model-value="emit('update:modelValue', { ...modelValue, reply_private: !!$event })" :label="t('允许回复私聊', 'Allow private replies')" color="primary" hide-details inset />
    <v-switch v-for="group in groups" :key="group.id" :model-value="modelValue.reply_groups?.[group.id] !== false" @update:model-value="emit('update:modelValue', { ...modelValue, reply_groups: { ...modelValue.reply_groups, [group.id]: !!$event } })" :label="t('允许回复群内消息 · ', 'Allow group replies · ') + group.name" color="primary" hide-details inset />
    <p class="text-caption text-medium-emphasis">{{ t('群聊开启回复后仍需明确 @ 机器人。关闭不删除会话或历史。', 'Group replies still require an explicit mention. Disabling preserves sessions and history.') }}</p>
    <v-divider />
    <h3 class="text-subtitle-1">{{ t('主动发送授权', 'Proactive sending') }}</h3>
    <v-switch :model-value="props.modelValue.proactive_send?.enabled === true" @update:model-value="emit('update:modelValue', { ...props.modelValue, proactive_send: { ...(props.modelValue.proactive_send || {}), enabled: !!$event } })" :label="t('允许主动发送和定时消息', 'Allow proactive and scheduled messages')" color="primary" hide-details inset />
    <v-select :model-value="modelValue.proactive_send?.targets || []" :items="proactiveTargets" item-title="title" item-value="value" multiple chips closable-chips variant="outlined" :label="t('允许主动发送的目标', 'Authorized proactive targets')" @update:model-value="emit('update:modelValue', { ...modelValue, proactive_send: { ...modelValue.proactive_send, targets: $event } })" />
    <v-btn variant="text" :loading="loadingTargets" @click="loadTargets">{{ t('刷新已知私聊目标', 'Refresh known private targets') }}</v-btn>
    <p v-if="targetError" class="text-error">{{ targetError }}</p>
    <p v-if="modelValue.proactive_send?.enabled && !(modelValue.proactive_send?.targets || []).length" class="text-warning">{{ t('尚无可主动发送目标', 'No authorized proactive target') }}</p>
    <p class="text-caption text-medium-emphasis">{{ t('默认关闭；仅发送到已确认的本机器人会话，两个旺商聊机器人互相排除。', 'Disabled by default; only confirmed sessions are eligible, and Wangshangliao bots exclude each other.') }}</p>
    <v-divider />
    <h3 class="text-subtitle-1">{{ t('机器人群管授权', 'Bot moderation capabilities') }}</h3>
    <p class="text-body-2 text-medium-emphasis">{{ t('这里配置当前机器人在每个群可以执行的动作，不配置其他成员对机器人的控制权限。', 'Configure what this bot can do in each group. This does not configure who can control the bot.') }}</p>
    <v-switch :model-value="policy.enabled || false" @update:model-value="set('enabled', !!$event)" :label="t('启用机器人群管', 'Enable bot moderation')" color="primary" hide-details inset />
    <v-select v-model="permissionGroup" :items="groups" item-title="name" item-value="id" :label="t('选择授权群', 'Group')" variant="outlined" />
    <v-alert v-if="!permissionGroup" type="info" variant="tonal">{{ t('请先在上方勾选启用群聊。', 'Enable a group above first.') }}</v-alert>
    <template v-if="permissionGroup">
      <v-checkbox v-for="item in actions" :key="item.value" :model-value="groupActions.includes(item.value)" @update:model-value="toggle(item.value, !!$event)" :label="item.title" hide-details density="compact" />
      <v-switch :model-value="policy.card_auto[permissionGroup] === true" @update:model-value="set('card_auto', { ...policy.card_auto, [permissionGroup]: !!$event })" :label="t('自动规范本群普通成员名片', 'Automatically normalize ordinary member cards in this group')" color="primary" hide-details inset />
      <p class="text-caption text-medium-emphasis">{{ t('默认关闭；需同时授权名片修改。开启后每五分钟检查完整目录，不调用 AI。请先保存配置。', 'Disabled by default; also requires card permission. Scans complete rosters every five minutes without AI. Save configuration first.') }}</p>
    </template>
    <v-text-field type="number" :model-value="policy.cooldown_seconds ?? 60" @update:model-value="set('cooldown_seconds', Number($event))" :label="t('每群处罚冷却（秒）', 'Per-group penalty cooldown (seconds)')" :min="10" :max="86400" variant="outlined" />
    <v-switch :model-value="policy.automation_enabled || false" @update:model-value="set('automation_enabled', !!$event)" :label="t('违规关键词规则', 'Violation keyword rules')" color="primary" hide-details inset />
    <template v-if="policy.automation_enabled">
      <v-combobox :model-value="policy.mute_keywords" @update:model-value="set('mute_keywords', $event)" :label="t('禁言关键词', 'Mute keywords')" multiple chips closable-chips variant="outlined" />
      <v-combobox :model-value="policy.kick_keywords" @update:model-value="set('kick_keywords', $event)" :label="t('踢出关键词', 'Removal keywords')" multiple chips closable-chips variant="outlined" />
      <v-switch :model-value="policy.recall_enabled" @update:model-value="set('recall_enabled', !!$event)" :label="t('首次违规起撤回消息', 'Recall from first violation')" color="primary" hide-details inset />
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { sessionApi } from '@/api/v1';
import { useI18n } from '@/i18n/composables';
const props = defineProps<{ modelValue: Record<string, any>; groups: Array<{ id: string; name: string }> }>();
const emit = defineEmits(['update:modelValue']);
const { locale } = useI18n();
const t = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en;
const privateTargets = ref<Array<{title: string; value: string}>>([]);
const loadingTargets = ref(false);
const targetError = ref('');
const proactiveTargets = computed(() => [...props.groups.map(group => ({ title: t('群 · ', 'Group · ') + group.name, value: group.id })), ...privateTargets.value]);
async function loadTargets() {
  const instance = props.modelValue.id;
  if (!instance) return;
  loadingTargets.value = true;
  targetError.value = '';
  try {
    const items: Array<{title: string; value: string}> = [];
    for (let page = 1; page <= 100; page++) {
      const response = await sessionApi.list({platform: instance, message_type: 'private', page, page_size: 100});
      const data = response.data.data;
      for (const item of data.sessions || []) {
        const value = String(item.session_id || '').replace(/^[^/]+\//, '');
        if (value.startsWith('private/')) items.push({title: item.display_name || value, value});
      }
      if (page * 100 >= data.total) break;
    }
    if (instance === props.modelValue.id) privateTargets.value = items;
  } catch { targetError.value = t('目录刷新失败，保留已保存授权。', 'Directory refresh failed; saved grants are preserved.'); }
  finally { loadingTargets.value = false; }
}
watch(() => props.modelValue.id, () => { privateTargets.value = []; void loadTargets(); }, {immediate: true});
const policy = computed(() => {
  const old = props.modelValue.moderation || {};
  return { card_auto: old.card_auto || {}, enabled: old.enabled === true, permissions: Object.fromEntries(Object.entries(old.permissions || {}).filter(([key, value]) => /^\d+$/.test(key) && Array.isArray(value))), automation_enabled: old.automation_enabled === true, keywords: old.keywords || [], mute_keywords: old.mute_keywords ?? old.keywords ?? [], kick_keywords: old.kick_keywords || [], recall_enabled: old.recall_enabled === true, cooldown_seconds: old.cooldown_seconds ?? 60 };
});
const permissionGroup = ref(props.modelValue.enabled_groups?.[0] || '');
watch(() => [props.modelValue.id, ...(props.modelValue.enabled_groups || [])], () => { if (!(props.modelValue.enabled_groups || []).includes(permissionGroup.value)) permissionGroup.value = props.modelValue.enabled_groups?.[0] || ''; });
const groupActions = computed<string[]>(() => { const value = policy.value.permissions[permissionGroup.value]; return Array.isArray(value) ? value : []; });
const set = (key: string, value: any) => emit('update:modelValue', { ...props.modelValue, moderation: { ...policy.value, [key]: value } });
const toggle = (action: string, enabled: boolean) => set('permissions', { ...policy.value.permissions, [permissionGroup.value]: enabled ? [...groupActions.value, action] : groupActions.value.filter((item: string) => item !== action) });
const actions = computed(() => [
  { value: 'cleanup', title: t('清理封禁／注销账号（移出群聊）', 'Remove banned / cancelled accounts') },
  { value: 'rename', title: t('修改普通成员群名片', 'Rename ordinary member cards') },
  { value: 'mute', title: t('成员禁言', 'Mute member') },
  { value: 'kick', title: t('移除成员', 'Remove member') },
  { value: 'recall', title: t('撤回违规消息', 'Recall violation') },
  { value: 'unmute', title: t('成员解禁', 'Unmute member') },
  { value: 'announce', title: t('发布公告', 'Publish announcement') },
  { value: 'mute_all', title: t('全员禁言', 'Mute all members') },
  { value: 'unmute_all', title: t('解除全员禁言', 'Unmute all members') },
]);
</script>
