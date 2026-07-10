import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TextInput, Modal } from 'react-native';
import type { StackScreenProps } from '@react-navigation/stack';
import { useNavigation } from '@react-navigation/native';
import type { AppStackParamList } from '../navigation/types';
import { useThemeColors } from '../context/ThemeContext';
import { useToast } from '../context/ToastContext';
import { AppButton } from '../components/AppButton';
import { AssignmentPicker, AssignmentPerson, selectedPeopleLabel } from '../components/AssignmentPicker';
import { Chip } from '../components/Chip';
import * as api from '../api/omniusApi';
import type { Alarm } from '../api/types';
import { formatAlarmDateTime, formatRelative } from '../utils/format';
import { useDemoLive } from '../demo/DemoLiveProvider';

type Props = StackScreenProps<AppStackParamList, 'AlertDetail'>;

export function AlertDetailScreen({ route }: Props) {
  const { alarmId } = route.params;
  const { seq: demoLiveSeq } = useDemoLive();
  const c = useThemeColors();
  const toast = useToast();
  const nav = useNavigation<any>();
  const [alarm, setAlarm] = useState<Alarm | null>(null);
  const [busy, setBusy] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [resolveOpen, setResolveOpen] = useState(false);
  const [resolveNote, setResolveNote] = useState('');

  React.useEffect(() => {
    (async () => {
      try {
        const a = await api.fetchAlarm(alarmId);
        setAlarm(a);
      } catch {
        toast.error('Alert not found');
        nav.goBack();
      }
    })();
  }, [alarmId, nav, toast, demoLiveSeq]);

  const reload = async () => {
    const a = await api.fetchAlarm(alarmId);
    setAlarm(a);
  };

  const assignAlert = async (people: AssignmentPerson[]) => {
    if (!alarm) return;
    setBusy(true);
    try {
      const assignees = selectedPeopleLabel(people);
      await api.acknowledgeAlarm(alarm.id, `Assigned to ${assignees}`);
      toast.show(`Assigned to ${assignees}`);
      setAssignOpen(false);
      await reload();
    } catch {
      toast.error('Could not assign alert');
    } finally {
      setBusy(false);
    }
  };

  const resolve = async () => {
    if (!alarm) return;
    setBusy(true);
    try {
      if (!alarm.is_acknowledged) {
        await api.acknowledgeAlarm(alarm.id, resolveNote.trim() || undefined);
      }
      await api.clearAlarm(alarm.id);
      toast.show('Marked as resolved');
      setResolveOpen(false);
      nav.goBack();
    } catch {
      toast.error('Could not update');
    } finally {
      setBusy(false);
    }
  };

  if (!alarm) {
    return (
      <View style={[styles.c, { backgroundColor: c.bg }]}>
        <Text style={{ color: c.muted }}>Loading…</Text>
      </View>
    );
  }

  const active = alarm.is_active && !alarm.is_acknowledged;
  const acked = alarm.is_acknowledged && alarm.is_active;
  const resolved = !alarm.is_active;

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView contentContainerStyle={styles.pad}>
        <Text style={[styles.title, { color: c.text }]}>{alarm.message}</Text>
        <View style={styles.row}>
          <Chip label={alarm.severity} tone={alarm.severity === 'critical' ? 'danger' : 'warn'} />
          <Chip label={resolved ? 'Resolved' : acked ? 'Acknowledged' : 'Active'} />
        </View>

        <Text style={[styles.h, { color: c.text }]}>Summary</Text>
        <Text style={[styles.p, { color: c.muted }]}>Code: {alarm.alarm_code}</Text>
        <Text style={[styles.p, { color: c.muted }]}>Raised: {formatAlarmDateTime(alarm.occurred_at)}</Text>
        <Text style={[styles.p, { color: c.muted }]}>
          Updated:{' '}
          {formatRelative(alarm.cleared_at ?? alarm.acknowledged_at ?? alarm.occurred_at)}
        </Text>

        <Text style={[styles.h, { color: c.text }]}>Details</Text>
        <Text style={[styles.p, { color: c.text }]}>{alarm.description || '—'}</Text>

        {active ? (
          <>
            <AppButton title="Assign" onPress={() => setAssignOpen(true)} loading={busy} style={{ marginTop: 16 }} />
            <AppButton title="Mark as resolved" variant="secondary" onPress={() => setResolveOpen(true)} style={{ marginTop: 10 }} />
          </>
        ) : null}
        {acked ? (
          <>
            <AppButton title="Mark as resolved" onPress={() => setResolveOpen(true)} loading={busy} style={{ marginTop: 16 }} />
          </>
        ) : null}

        <AppButton
          title="Alert admin"
          variant="secondary"
          onPress={() => nav.navigate('ContactAdminApp')}
          style={{ marginTop: 12 }}
        />
      </ScrollView>

      <AssignmentPicker
        visible={assignOpen}
        title="Assign alert"
        confirmTitle="Assign"
        loading={busy}
        onCancel={() => setAssignOpen(false)}
        onConfirm={(people) => void assignAlert(people)}
      />

      <Modal visible={resolveOpen} transparent animationType="slide">
        <View style={styles.modalBg}>
          <View style={[styles.sheet, { backgroundColor: c.card }]}>
            <Text style={[styles.sh, { color: c.text }]}>What did you do?</Text>
            <TextInput
              value={resolveNote}
              onChangeText={setResolveNote}
              multiline
              placeholder="Short note (optional)"
              placeholderTextColor={c.muted}
              style={[styles.input, { borderColor: c.border, color: c.text }]}
            />
            <View style={{ flexDirection: 'row', gap: 10, marginTop: 12 }}>
              <AppButton title="Cancel" variant="secondary" onPress={() => setResolveOpen(false)} style={{ flex: 1 }} />
              <AppButton title="Resolve" onPress={resolve} loading={busy} style={{ flex: 1 }} />
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  c: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  pad: { padding: 16, paddingBottom: 40 },
  title: { fontSize: 22, fontWeight: '800' },
  row: { flexDirection: 'row', gap: 8, marginTop: 10, flexWrap: 'wrap' },
  h: { fontSize: 18, fontWeight: '800', marginTop: 18 },
  p: { fontSize: 16, marginTop: 6, lineHeight: 22 },
  modalBg: { flex: 1, backgroundColor: '#0008', justifyContent: 'flex-end' },
  sheet: { padding: 20, borderTopLeftRadius: 16, borderTopRightRadius: 16 },
  sh: { fontSize: 18, fontWeight: '800', marginBottom: 8 },
  input: { borderWidth: 2, borderRadius: 12, minHeight: 100, padding: 12, fontSize: 16, textAlignVertical: 'top' },
});
