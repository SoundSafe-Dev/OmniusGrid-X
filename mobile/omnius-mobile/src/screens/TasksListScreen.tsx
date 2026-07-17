import React, { useCallback, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Pressable,
  RefreshControl,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { useThemeColors } from '../context/ThemeContext';
import { Chip } from '../components/Chip';
import { AppButton } from '../components/AppButton';
import { AssignmentPicker, AssignmentPerson, selectedPeopleLabel } from '../components/AssignmentPicker';
import type { Task } from '../api/types';
import type { MainTabParamList, TaskSegment } from '../navigation/types';
import {
  filterTasksBySegment,
  primaryTaskAction,
  taskSegment,
  columnIdByType,
} from '../utils/taskBuckets';
import * as api from '../api/omniusApi';

type Route = RouteProp<MainTabParamList, 'TasksTab'>;

const SEGMENTS: { key: TaskSegment; label: string }[] = [
  { key: 'new', label: 'New' },
  { key: 'in_progress', label: 'In progress' },
  { key: 'completed', label: 'Completed' },
];

export function TasksListScreen() {
  const c = useThemeColors();
  const insets = useSafeAreaInsets();
  const route = useRoute<Route>();
  const navigation = useNavigation<any>();
  const { kanban } = useAuth();
  const toast = useToast();
  const [segment, setSegment] = useState<TaskSegment>('new');
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [assigningTask, setAssigningTask] = useState<Task | null>(null);

  React.useEffect(() => {
    const s = route.params?.segment;
    if (s) {
      setSegment(s);
      navigation.setParams({ segment: undefined });
    }
  }, [route.params?.segment, navigation]);

  const colMap = useMemo(
    () => new Map(kanban.columns.map((x) => [x.id, x])),
    [kanban.columns]
  );

  const list = useMemo(
    () => filterTasksBySegment(kanban.tasks, kanban.columns, segment),
    [kanban.tasks, kanban.columns, segment]
  );

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await kanban.refresh();
    } catch {
      toast.error('Could not refresh');
    } finally {
      setRefreshing(false);
    }
  };

  const runPrimary = async (task: Task, people: AssignmentPerson[]) => {
    const action = primaryTaskAction(colMap, task);
    setBusyId(task.id);
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
        toast.show('Task marked completed');
      } else if (action === 'reopen') {
        const tid = columnIdByType(kanban.columns, 'triage');
        if (!tid) throw new Error('missing triage');
        await api.moveTask(task.id, tid);
        toast.show('Task reopened');
      }
      await kanban.refresh();
    } catch (e: unknown) {
      toast.error('Could not update. Check connection and try again.');
    } finally {
      setBusyId(null);
      setAssigningTask(null);
    }
  };

  const priorityTone = (p: string) =>
    p === 'critical' || p === 'emergency' ? 'danger' : p === 'high' ? 'warn' : 'default';

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={[styles.segRow, { borderBottomColor: c.border, paddingTop: insets.top }]}>
        {SEGMENTS.map((s) => {
          const on = segment === s.key;
          return (
            <Pressable
              key={s.key}
              onPress={() => setSegment(s.key)}
              style={[
                styles.segBtn,
                on && { borderBottomWidth: 3, borderBottomColor: c.primary },
              ]}
            >
              <Text style={[styles.segTxt, { color: on ? c.primary : c.muted }]}>{s.label}</Text>
            </Pressable>
          );
        })}
      </View>

      <FlatList
        data={list}
        keyExtractor={(item) => item.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        contentContainerStyle={{ padding: 12, paddingBottom: 100 }}
        ListEmptyComponent={
          <Text style={{ color: c.muted, textAlign: 'center', marginTop: 32, fontSize: 16 }}>No tasks in this column</Text>
        }
        renderItem={({ item }) => {
          const seg = taskSegment(colMap, item);
          const action = primaryTaskAction(colMap, item);
          const label =
            action === 'approve' || action === 'start'
              ? 'Assign'
              : action === 'complete'
                ? 'Complete'
                : action === 'reopen'
                  ? 'Reopen'
                  : null;
          return (
            <Pressable
              onPress={() => navigation.navigate('TaskDetail', { taskId: item.id })}
              style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}
            >
              <View style={styles.cardTop}>
                <Text style={[styles.title, { color: c.text }]} numberOfLines={2}>
                  {item.title}
                </Text>
                {label ? (
                  <AppButton
                    title={label}
                    onPress={() => {
                      if (action === 'approve' || action === 'start') {
                        setAssigningTask(item);
                      } else {
                        void runPrimary(item, []);
                      }
                    }}
                    loading={busyId === item.id}
                    style={{ minWidth: 110, minHeight: 44, paddingHorizontal: 8 }}
                  />
                ) : null}
              </View>
              {item.description ? (
                <Text style={[styles.desc, { color: c.muted }]} numberOfLines={2}>
                  {item.description}
                </Text>
              ) : null}
              <View style={styles.row}>
                {item.asset_id ? <Chip label="Asset linked" /> : null}
                <Chip label={item.priority} tone={priorityTone(item.priority)} />
                <Text style={[styles.meta, { color: c.muted }]}>
                  {item.assigned_at ? `Assigned ${new Date(item.assigned_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
                </Text>
              </View>
              <Text style={[styles.st, { color: c.muted }]}>Status: {seg}</Text>
            </Pressable>
          );
        }}
      />
      <AssignmentPicker
        visible={assigningTask != null}
        title="Assign task"
        confirmTitle="Assign"
        loading={assigningTask ? busyId === assigningTask.id : false}
        onCancel={() => setAssigningTask(null)}
        onConfirm={(people) => {
          if (assigningTask) void runPrimary(assigningTask, people);
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  segRow: { flexDirection: 'row', borderBottomWidth: 1 },
  segBtn: { flex: 1, minHeight: 54, paddingVertical: 14, alignItems: 'center', justifyContent: 'center' },
  segTxt: { fontSize: 16, fontWeight: '700' },
  card: {
    borderRadius: 14,
    borderWidth: 1,
    padding: 14,
    marginBottom: 10,
  },
  cardTop: { flexDirection: 'row', gap: 8, alignItems: 'flex-start', justifyContent: 'space-between' },
  title: { flex: 1, fontSize: 18, fontWeight: '800' },
  desc: { fontSize: 15, marginTop: 6 },
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 10, alignItems: 'center' },
  meta: { fontSize: 14 },
  st: { marginTop: 8, fontSize: 14 },
});
