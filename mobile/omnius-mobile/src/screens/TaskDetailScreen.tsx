import React, { useCallback, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  Modal,
  RefreshControl,
} from 'react-native';
import type { StackScreenProps } from '@react-navigation/stack';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { useThemeColors } from '../context/ThemeContext';
import { AppButton } from '../components/AppButton';
import { AssignmentPicker, AssignmentPerson, selectedPeopleLabel } from '../components/AssignmentPicker';
import { Chip } from '../components/Chip';
import type { AppStackParamList } from '../navigation/types';
import type { Task, TaskComment } from '../api/types';
import * as api from '../api/omniusApi';
import { columnIdByType, primaryTaskAction } from '../utils/taskBuckets';
import { useNavigation } from '@react-navigation/native';
import { useDemoLive } from '../demo/DemoLiveProvider';

type Props = StackScreenProps<AppStackParamList, 'TaskDetail'>;

export function TaskDetailScreen({ route }: Props) {
  const { taskId } = route.params;
  const { seq: demoLiveSeq } = useDemoLive();
  const c = useThemeColors();
  const toast = useToast();
  const nav = useNavigation();
  const { kanban } = useAuth();
  const [task, setTask] = useState<Task | null>(null);
  const [comments, setComments] = useState<TaskComment[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);

  const colMap = useMemo(
    () => new Map(kanban.columns.map((x) => [x.id, x])),
    [kanban.columns]
  );

  const load = useCallback(async () => {
    const [t, cm] = await Promise.all([
      api.fetchTask(taskId),
      api.fetchTaskComments(taskId).catch(() => []),
    ]);
    setTask(t);
    setComments(cm);
  }, [taskId, demoLiveSeq]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await load();
      await kanban.refresh();
    } finally {
      setRefreshing(false);
    }
  };

  const action = task ? primaryTaskAction(colMap, task) : null;

  const doPrimary = async (people: AssignmentPerson[] = []) => {
    if (!task) return;
    setBusy(true);
    try {
      const assignees = selectedPeopleLabel(people);
      if (action === 'approve') {
        await api.approveTask(task.id, 'approve');
        await api.addTaskComment(task.id, `Assigned to ${assignees}`).catch(() => undefined);
        toast.show(`Assigned to ${assignees}`);
      } else if (action === 'start') {
        await api.startTask(task.id);
        await api.addTaskComment(task.id, `Assigned to ${assignees}`).catch(() => undefined);
        toast.show(`Assigned to ${assignees}`);
      } else if (action === 'complete') {
        await api.completeTask(task.id);
        toast.show('Task marked as completed');
      } else if (action === 'reopen') {
        const tid = columnIdByType(kanban.columns, 'triage');
        if (!tid) throw new Error('no triage');
        await api.moveTask(task.id, tid);
        toast.show('Task reopened');
      }
      await load();
      await kanban.refresh();
      nav.goBack();
    } catch {
      toast.error('Could not update. Check connection and try again.');
    } finally {
      setBusy(false);
      setAssignOpen(false);
    }
  };

  const saveNote = async () => {
    if (!note.trim() || !task) return;
    setBusy(true);
    try {
      await api.addTaskComment(task.id, note.trim());
      toast.show('Note saved');
      setNote('');
      setNoteOpen(false);
      await load();
    } catch {
      toast.error('Could not save note');
    } finally {
      setBusy(false);
    }
  };

  if (!task) {
    return (
      <View style={[styles.center, { backgroundColor: c.bg }]}>
        <Text style={{ color: c.muted }}>Loading…</Text>
      </View>
    );
  }

  const col = colMap.get(task.column_id);
  const primaryLabel =
    action === 'approve' || action === 'start'
      ? 'Assign'
      : action === 'complete'
        ? 'Mark as completed'
        : action === 'reopen'
          ? 'Reopen task'
          : null;

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <ScrollView
        contentContainerStyle={styles.pad}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        <Text style={[styles.title, { color: c.text }]}>{task.title}</Text>
        <View style={styles.row}>
          <Chip label={col?.column_type ?? task.status} />
          <Chip label={task.priority} />
        </View>

        <Text style={[styles.section, { color: c.text }]}>Info</Text>
        <Text style={[styles.body, { color: c.muted }]}>Task type: {task.task_type}</Text>
        <Text style={[styles.body, { color: c.muted }]}>
          Assigned: {task.assigned_at ? new Date(task.assigned_at).toLocaleString() : '—'}
        </Text>
        <Text style={[styles.body, { color: c.muted }]}>
          Due: {task.due_date ? new Date(task.due_date).toLocaleString() : '—'}
        </Text>

        <Text style={[styles.section, { color: c.text }]}>Description</Text>
        <Text style={[styles.body, { color: c.text }]}>{task.description || '—'}</Text>

        {primaryLabel ? (
          <AppButton
            title={primaryLabel}
            onPress={() => {
              if (action === 'approve' || action === 'start') {
                setAssignOpen(true);
              } else {
                void doPrimary();
              }
            }}
            loading={busy}
            style={{ marginTop: 16 }}
          />
        ) : null}
        <AppButton
          title="Alert admin"
          variant="secondary"
          onPress={() => nav.navigate('ContactAdminApp' as never)}
          style={{ marginTop: 10 }}
        />

        <Text style={[styles.section, { color: c.text }]}>Notes</Text>
        {comments.slice(0, 8).map((cm) => (
          <View key={cm.id} style={[styles.note, { borderColor: c.border }]}>
            <Text style={{ color: c.text }}>{cm.content}</Text>
            <Text style={{ color: c.muted, fontSize: 13, marginTop: 4 }}>
              {new Date(cm.created_at).toLocaleString()}
            </Text>
          </View>
        ))}
        <AppButton title="Add note" variant="ghost" onPress={() => setNoteOpen(true)} style={{ marginTop: 8 }} />
      </ScrollView>

      <AssignmentPicker
        visible={assignOpen}
        title="Assign task"
        confirmTitle="Assign"
        loading={busy}
        onCancel={() => setAssignOpen(false)}
        onConfirm={(people) => void doPrimary(people)}
      />

      <Modal visible={noteOpen} animationType="slide" transparent>
        <View style={styles.modalBg}>
          <View style={[styles.sheet, { backgroundColor: c.card }]}>
            <Text style={[styles.sheetTitle, { color: c.text }]}>Add note</Text>
            <TextInput
              value={note}
              onChangeText={setNote}
              multiline
              placeholder="Note for admins…"
              placeholderTextColor={c.muted}
              style={[styles.input, { color: c.text, borderColor: c.border }]}
            />
            <View style={{ flexDirection: 'row', gap: 10, marginTop: 12 }}>
              <AppButton title="Cancel" variant="secondary" onPress={() => setNoteOpen(false)} style={{ flex: 1 }} />
              <AppButton title="Save note" onPress={saveNote} loading={busy} style={{ flex: 1 }} />
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  pad: { padding: 16, paddingBottom: 48 },
  title: { fontSize: 22, fontWeight: '800' },
  row: { flexDirection: 'row', gap: 8, marginTop: 10, flexWrap: 'wrap' },
  section: { fontSize: 18, fontWeight: '800', marginTop: 18 },
  body: { fontSize: 16, marginTop: 6, lineHeight: 22 },
  note: { borderWidth: 1, borderRadius: 10, padding: 10, marginTop: 8 },
  modalBg: { flex: 1, backgroundColor: '#0008', justifyContent: 'flex-end' },
  sheet: { padding: 20, borderTopLeftRadius: 16, borderTopRightRadius: 16 },
  sheetTitle: { fontSize: 18, fontWeight: '800', marginBottom: 10 },
  input: { borderWidth: 2, borderRadius: 12, minHeight: 120, padding: 12, fontSize: 17, textAlignVertical: 'top' },
});
