import React, { useCallback, useState } from 'react';
import { View, Text, StyleSheet, FlatList, Pressable, RefreshControl } from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useThemeColors } from '../context/ThemeContext';
import { useToast } from '../context/ToastContext';
import { useAuth } from '../context/AuthContext';
import { Chip } from '../components/Chip';
import { AppButton } from '../components/AppButton';
import { AssignmentPicker, AssignmentPerson, selectedPeopleLabel } from '../components/AssignmentPicker';
import type { Alarm } from '../api/types';
import * as api from '../api/omniusApi';
import type { MainTabParamList } from '../navigation/types';
import { formatAlarmDateTime } from '../utils/format';
import { useDemoLive } from '../demo/DemoLiveProvider';
import { HIT, PAD, TYPE } from '../theme/supervisorTouch';

type Filter = 'active' | 'ack' | 'resolved';

type R = RouteProp<MainTabParamList, 'AlertsTab'>;

export function AlertsListScreen() {
  const c = useThemeColors();
  const insets = useSafeAreaInsets();
  const { seq: demoLiveSeq } = useDemoLive();
  const { user } = useAuth();
  const navigation = useNavigation<any>();
  const route = useRoute<R>();
  const toast = useToast();
  const [filter, setFilter] = useState<Filter>('active');
  const [rows, setRows] = useState<Alarm[]>([]);
  const [summary, setSummary] = useState<{ total: number; active: number; ackDerived: number } | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [assigningAlarm, setAssigningAlarm] = useState<Alarm | null>(null);

  React.useEffect(() => {
    const f = route.params?.filter;
    if (f) {
      setFilter(f);
      navigation.setParams({ filter: undefined });
    }
  }, [route.params?.filter, navigation]);

  const load = useCallback(async () => {
    try {
      const orgId = user?.organization_id;
      const listPromise =
        filter === 'active'
          ? api.fetchAlarms({ is_active: true, acknowledged: false, limit: 200 })
          : filter === 'ack'
            ? api.fetchAlarms({ is_active: true, acknowledged: true, limit: 200 })
            : api.fetchAlarms({ is_active: false, limit: 200 });

      const [data, allRecent, activePayload] = await Promise.all([
        listPromise,
        api.fetchAlarms({ limit: 200 }),
        orgId ? api.fetchActiveAlarms(orgId).catch(() => null) : Promise.resolve(null),
      ]);

      setRows(data);
      setSummary({
        total: allRecent.length,
        active: activePayload?.count ?? 0,
        ackDerived: Math.max(0, allRecent.length - (activePayload?.count ?? 0)),
      });
    } catch {
      toast.error('Could not load alerts');
    }
  }, [filter, toast, demoLiveSeq, user?.organization_id]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await load();
    } finally {
      setRefreshing(false);
    }
  };

  const assignAlert = async (alarm: Alarm, people: AssignmentPerson[]) => {
    setBusyId(alarm.id);
    try {
      const assignees = selectedPeopleLabel(people);
      await api.acknowledgeAlarm(alarm.id, `Assigned to ${assignees}`);
      toast.show(`Assigned to ${assignees}`);
      await load();
    } catch {
      toast.error('Could not update. Try again.');
    } finally {
      setBusyId(null);
      setAssigningAlarm(null);
    }
  };

  const sevTone = (s: string): 'default' | 'danger' | 'warn' =>
    s === 'critical' ? 'danger' : s === 'high' || s === 'medium' ? 'warn' : 'default';

  const SEGMENTS: [Filter, string][] = [
    ['active', 'Open'],
    ['ack', 'Handed off'],
    ['resolved', 'Closed'],
  ];

  const statusLabel = (item: Alarm) => {
    if (!item.is_active) return 'Closed';
    return item.is_acknowledged ? 'Seen' : 'Open';
  };

  const statusTone = (item: Alarm): 'default' | 'danger' | 'warn' | 'ok' => {
    if (!item.is_active) return 'ok';
    return item.is_acknowledged ? 'default' : 'warn';
  };

  const summaryHeader = (
    <View style={{ marginBottom: PAD.gap }}>
      <Text style={[styles.screenTitle, { color: c.text }]}>Alerts</Text>
      <View style={[styles.summaryRow, { marginTop: 14 }]}>
        <View style={[styles.sumCard, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={[styles.sumLbl, { color: c.muted }]}>Total</Text>
          <Text style={[styles.sumVal, { color: c.text }]}>{summary?.total ?? '—'}</Text>
        </View>
        <View style={[styles.sumCard, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={[styles.sumLbl, { color: c.muted }]}>Open</Text>
          <Text style={[styles.sumVal, { color: '#ef4444' }]}>{summary?.active ?? '—'}</Text>
        </View>
        <View style={[styles.sumCard, { backgroundColor: c.card, borderColor: c.border }]}>
          <Text style={[styles.sumLbl, { color: c.muted }]}>Seen</Text>
          <Text style={[styles.sumVal, { color: '#22c55e' }]}>{summary?.ackDerived ?? '—'}</Text>
        </View>
      </View>
      <Text style={[styles.historyTitle, { color: c.text }]}>List</Text>
    </View>
  );

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={[styles.segRow, { borderBottomColor: c.border, borderBottomWidth: 2, paddingTop: insets.top }]}>
        {SEGMENTS.map(([key, label]) => {
          const on = filter === key;
          return (
            <Pressable
              key={key}
              onPress={() => setFilter(key)}
              style={[
                styles.segBtn,
                on && { borderBottomWidth: 4, borderBottomColor: c.primary, marginBottom: -2 },
              ]}
            >
              <Text style={[styles.segTxt, { color: on ? c.primary : c.muted }]}>{label}</Text>
            </Pressable>
          );
        })}
      </View>

      <FlatList
        data={rows}
        keyExtractor={(x) => x.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        contentContainerStyle={{ padding: PAD.screen, paddingBottom: 120 }}
        ListEmptyComponent={
          <Text style={{ color: c.muted, textAlign: 'center', marginTop: 32, fontSize: TYPE.body }}>
            No alerts in this list.
          </Text>
        }
        renderItem={({ item }) => (
          <Pressable
            onPress={() => navigation.navigate('AlertDetail', { alarmId: item.id })}
            style={[styles.card, { backgroundColor: c.card, borderColor: c.border }]}
          >
            <View style={styles.cardInner}>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 10 }}>
                <Chip label={item.severity} tone={sevTone(item.severity)} size="touch" />
                <Chip label={statusLabel(item)} tone={statusTone(item)} size="touch" />
              </View>
              <Text style={[styles.title, { color: c.text }]} numberOfLines={5}>
                {item.message}
              </Text>
              <Text style={[styles.meta, { color: c.muted }]}>
                {item.alarm_code} · {formatAlarmDateTime(item.occurred_at)}
              </Text>
              {filter === 'active' && !item.is_acknowledged ? (
                <AppButton
                  title="Assign"
                  onPress={() => setAssigningAlarm(item)}
                  loading={busyId === item.id}
                  style={{ marginTop: 14, minHeight: HIT.button, alignSelf: 'stretch' }}
                />
              ) : null}
            </View>
          </Pressable>
        )}
      />
      <AssignmentPicker
        visible={assigningAlarm != null}
        title="Assign alert"
        confirmTitle="Assign"
        loading={assigningAlarm ? busyId === assigningAlarm.id : false}
        onCancel={() => setAssigningAlarm(null)}
        onConfirm={(people) => {
          if (assigningAlarm) void assignAlert(assigningAlarm, people);
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  segRow: { flexDirection: 'row' },
  segBtn: { flex: 1, minHeight: HIT.tab, alignItems: 'center', justifyContent: 'center', paddingVertical: 4 },
  segTxt: { fontSize: TYPE.label, fontWeight: '800' },
  screenTitle: { fontSize: TYPE.title, fontWeight: '900' },
  summaryRow: { flexDirection: 'row', gap: 10 },
  sumCard: {
    flex: 1,
    borderRadius: 16,
    borderWidth: 2,
    padding: 12,
    minHeight: 92,
    justifyContent: 'center',
  },
  sumLbl: { fontSize: TYPE.small, fontWeight: '700' },
  sumVal: { fontSize: 28, fontWeight: '900', marginTop: 6 },
  historyTitle: { fontSize: TYPE.section, fontWeight: '800', marginTop: 20, marginBottom: 6 },
  card: { borderRadius: 16, borderWidth: 2, marginBottom: 14 },
  cardInner: { padding: PAD.card },
  title: { fontSize: TYPE.body, fontWeight: '800', marginTop: 12, lineHeight: 26 },
  meta: { marginTop: 10, fontSize: TYPE.small, lineHeight: 22 },
});
