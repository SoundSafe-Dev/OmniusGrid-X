import React, { useCallback, useMemo, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, Pressable } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import { useThemeColors } from '../context/ThemeContext';
import { Chip } from '../components/Chip';
import * as api from '../api/omniusApi';
import type {
  ActiveAlarmsPayload,
  DashboardOverview,
  KanbanMetrics,
  TransportShipment,
  YardTrailer,
} from '../api/types';
import { greetingName, timeOfDayGreeting, formatAlarmDateTime } from '../utils/format';
import type { TaskSegment } from '../navigation/types';
import { useDemoLive } from '../demo/DemoLiveProvider';
import { HIT, PAD, TYPE } from '../theme/supervisorTouch';

function placeLabel(p: Record<string, unknown> | undefined): string {
  if (!p || typeof p !== 'object') return '';
  const city = p.city;
  const name = p.name;
  if (typeof city === 'string' && city.trim()) return city.trim();
  if (typeof name === 'string' && name.trim()) return name.trim();
  return '';
}

function routeLabel(s: TransportShipment): string {
  const a = placeLabel(s.origin);
  const b = placeLabel(s.destination);
  if (a && b) return `${a} → ${b}`;
  if (a) return a;
  if (b) return b;
  return '—';
}

function BigAction({
  title,
  subtitle,
  icon,
  onPress,
  badge,
  c,
}: {
  title: string;
  subtitle?: string;
  icon: React.ComponentProps<typeof Ionicons>['name'];
  onPress: () => void;
  badge?: number;
  c: ReturnType<typeof useThemeColors>;
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.bigAction,
        {
          backgroundColor: c.card,
          borderColor: c.border,
          opacity: pressed ? 0.92 : 1,
        },
      ]}
    >
      <View style={[styles.bigIconWrap, { backgroundColor: c.chip }]}>
        <Ionicons name={icon} size={28} color={c.primary} />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={[styles.bigActionTitle, { color: c.text }]}>{title}</Text>
        {subtitle ? <Text style={[styles.bigActionSub, { color: c.muted }]}>{subtitle}</Text> : null}
      </View>
      {badge != null && badge > 0 ? (
        <View style={[styles.badge, { backgroundColor: c.danger }]}>
          <Text style={styles.badgeTxt}>{badge > 99 ? '99+' : String(badge)}</Text>
        </View>
      ) : (
        <Ionicons name="chevron-forward" size={28} color={c.muted} />
      )}
    </Pressable>
  );
}

export function HomeScreen() {
  const c = useThemeColors();
  const { seq: demoLiveSeq } = useDemoLive();
  const { user, kanban } = useAuth();
  const toast = useToast();
  const navigation = useNavigation<any>();
  const [refreshing, setRefreshing] = useState(false);
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [metrics, setMetrics] = useState<KanbanMetrics | null>(null);
  const [active, setActive] = useState<ActiveAlarmsPayload | null>(null);
  const [trailers, setTrailers] = useState<YardTrailer[] | null>(null);
  const [shipments, setShipments] = useState<TransportShipment[] | null>(null);

  const load = useCallback(async () => {
    if (!user?.organization_id) return;
    const org = user.organization_id;
    try {
      const [ov, m, a, t, sh] = await Promise.all([
        api.fetchDashboardOverview(org).catch(() => null),
        api.fetchKanbanMetrics().catch(() => null),
        api.fetchActiveAlarms(org).catch(() => null),
        api.fetchYardTrailers(org).catch(() => null),
        api.fetchTransportShipments(org).catch(() => [] as TransportShipment[]),
      ]);
      setOverview(ov);
      setMetrics(m);
      setActive(a);
      setTrailers(Array.isArray(t) ? t : []);
      setShipments(Array.isArray(sh) ? sh : []);
    } catch {
      toast.error('Could not load. Pull down to try again.');
    }
  }, [user?.organization_id, toast, demoLiveSeq]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load])
  );

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await Promise.all([load(), kanban.refresh()]);
      toast.show('Updated');
    } catch {
      toast.error('Refresh failed');
    } finally {
      setRefreshing(false);
    }
  };

  const name = greetingName(user?.full_name);
  const greet = timeOfDayGreeting();

  const byCol = metrics?.tasks_by_column ?? {};
  const newTasksApprox = (byCol.backlog ?? 0) + (byCol.triage ?? 0);
  const inProg = (byCol.in_progress ?? 0) + (byCol.review ?? 0);
  const doneToday = metrics?.tasks_completed_today ?? 0;

  const yardStats = useMemo(() => {
    if (!trailers?.length) return { total: 0, inYard: 0, docked: 0, checkedOut: 0 };
    let inYard = 0;
    let docked = 0;
    let checkedOut = 0;
    for (const x of trailers) {
      if (x.status === 'docked') docked += 1;
      else if (x.status === 'checked_out') checkedOut += 1;
      else if (x.status === 'yard' || x.status === 'checked_in') inYard += 1;
    }
    return { total: trailers.length, inYard, docked, checkedOut };
  }, [trailers]);

  const tmsStats = useMemo(() => {
    const rows = shipments ?? [];
    return {
      total: rows.length,
      inTransit: rows.filter((s) => s.status === 'in_transit').length,
      planned: rows.filter((s) => s.status === 'planned').length,
      delivered: rows.filter((s) => s.status === 'delivered').length,
    };
  }, [shipments]);

  const packmlEntries = useMemo(() => {
    const map = overview?.assets_by_state ?? {};
    return Object.entries(map)
      .filter(([, n]) => (n ?? 0) > 0)
      .sort((a, b) => b[1] - a[1]);
  }, [overview]);

  const previewAlarms = (active?.alarms ?? []).slice(0, 4);
  const activeCount = active?.count ?? overview?.active_alarms ?? 0;

  const sevTone = (s: string): 'default' | 'danger' | 'warn' =>
    s === 'critical' ? 'danger' : s === 'high' ? 'warn' : 'default';

  const goTasks = (segment: TaskSegment) => {
    navigation.navigate('TasksTab', { segment });
  };

  const statBig = (label: string, value: string | number, accent?: string) => (
    <View style={[styles.statCard, { backgroundColor: c.card, borderColor: c.border }]}>
      <Text style={[styles.statNum, { color: accent ?? c.text }]}>{value}</Text>
      <Text style={[styles.statLbl, { color: c.muted }]}>{label}</Text>
    </View>
  );

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: c.bg }}
      contentContainerStyle={styles.pad}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
    >
      <View style={styles.headerRow}>
        <View style={{ flex: 1 }}>
          <Text style={[styles.hero, { color: c.text }]}>Floor overview</Text>
          <Text style={[styles.greetLine, { color: c.muted }]}>
            {greet}, {name}
          </Text>
        </View>
        <View style={[styles.liveBlock, { borderColor: c.border }]}>
          <View style={styles.liveDot} />
          <Text style={[styles.liveWord, { color: c.text }]}>Live</Text>
        </View>
      </View>

      <Text style={[styles.sectionHdr, { color: c.text }]}>Go to</Text>
      <View style={{ gap: PAD.gap }}>
        <BigAction
          title="Alerts"
          subtitle={activeCount ? `${activeCount} need attention` : 'Nothing open right now'}
          icon="warning-outline"
          badge={activeCount > 0 ? activeCount : undefined}
          onPress={() => navigation.navigate('AlertsTab', { filter: 'active' })}
          c={c}
        />
        <BigAction
          title="Equipment"
          subtitle="Machines and lines"
          icon="cube-outline"
          onPress={() => navigation.navigate('AssetsTab', { tab: 'machines' })}
          c={c}
        />
        <BigAction
          title="Trailers"
          subtitle="Yard and docks"
          icon="bus-outline"
          onPress={() => navigation.navigate('AssetsTab', { tab: 'trucks' })}
          c={c}
        />
        <BigAction
          title="Work for today"
          subtitle={`${newTasksApprox} new · ${inProg} in progress · ${doneToday} done today`}
          icon="clipboard-outline"
          onPress={() => goTasks('new')}
          c={c}
        />
      </View>

      <Text style={[styles.sectionHdr, { color: c.text, marginTop: 28 }]}>At a glance</Text>
      <View style={styles.statGrid}>
        {statBig('Equipment count', overview?.total_assets ?? '—')}
        {statBig('Equipment running', overview?.active_assets ?? '—', '#22c55e')}
        {statBig('Open alerts', activeCount, activeCount > 0 ? '#f87171' : undefined)}
        {statBig('Serious alerts', overview?.critical_alarms ?? '—', (overview?.critical_alarms ?? 0) > 0 ? '#ef4444' : undefined)}
      </View>

      <Text style={[styles.sectionHdr, { color: c.text, marginTop: 24 }]}>Machine states</Text>
      <Text style={[styles.sectionHelp, { color: c.muted }]}>How many machines are in each state right now.</Text>
      <View style={[styles.panel, { backgroundColor: c.card, borderColor: c.border }]}>
        {packmlEntries.length === 0 ? (
          <Text style={[styles.body, { color: c.muted }]}>No breakdown yet.</Text>
        ) : (
          packmlEntries.map(([state, count]) => (
            <View key={state} style={[styles.stateRow, { borderBottomColor: c.border }]}>
              <Text style={[styles.stateName, { color: c.text }]} numberOfLines={2}>
                {state}
              </Text>
              <Text style={[styles.stateCount, { color: c.primary }]}>{count}</Text>
            </View>
          ))
        )}
      </View>

      <View style={styles.sectionRow}>
        <Text style={[styles.sectionHdr, { color: c.text, marginTop: 0, marginBottom: 0 }]}>Open alerts</Text>
        <Pressable
          hitSlop={12}
          onPress={() => navigation.navigate('AlertsTab', { filter: 'active' })}
          style={styles.seeAllBtn}
        >
          <Text style={[styles.seeAllTxt, { color: c.primary }]}>See all</Text>
        </Pressable>
      </View>
      <View style={{ gap: PAD.gap }}>
        {previewAlarms.length === 0 ? (
          <View style={[styles.panel, { backgroundColor: c.card, borderColor: c.border }]}>
            <Text style={[styles.body, { color: c.muted }]}>No open alerts. Good run.</Text>
          </View>
        ) : (
          previewAlarms.map((alarm) => (
            <Pressable
              key={alarm.id}
              onPress={() => navigation.navigate('AlertDetail', { alarmId: alarm.id })}
              style={[styles.alarmCard, { backgroundColor: c.card, borderColor: c.border }]}
            >
              <Chip label={alarm.severity} tone={sevTone(alarm.severity)} size="touch" />
              <Text style={[styles.alarmTitle, { color: c.text }]} numberOfLines={4}>
                {alarm.message}
              </Text>
              <Text style={[styles.alarmMeta, { color: c.muted }]}>
                {formatAlarmDateTime(alarm.occurred_at)}
              </Text>
            </Pressable>
          ))
        )}
      </View>

      <Text style={[styles.sectionHdr, { color: c.text, marginTop: 28 }]}>Yard</Text>
      <View style={[styles.panel, { backgroundColor: c.card, borderColor: c.border }]}>
        {trailers == null ? (
          <Text style={[styles.body, { color: c.muted }]}>Loading…</Text>
        ) : (
          <View style={styles.yardGrid}>
            <View style={styles.yardBox}>
              <Text style={[styles.yardNum, { color: c.text }]}>{yardStats.total}</Text>
              <Text style={[styles.yardWord, { color: c.muted }]}>Total</Text>
            </View>
            <View style={styles.yardBox}>
              <Text style={[styles.yardNum, { color: c.text }]}>{yardStats.inYard}</Text>
              <Text style={[styles.yardWord, { color: c.muted }]}>In yard</Text>
            </View>
            <View style={styles.yardBox}>
              <Text style={[styles.yardNum, { color: '#4ade80' }]}>{yardStats.docked}</Text>
              <Text style={[styles.yardWord, { color: c.muted }]}>At dock</Text>
            </View>
            <View style={styles.yardBox}>
              <Text style={[styles.yardNum, { color: c.text }]}>{yardStats.checkedOut}</Text>
              <Text style={[styles.yardWord, { color: c.muted }]}>Checked out</Text>
            </View>
          </View>
        )}
      </View>

      <Text style={[styles.sectionHdr, { color: c.text, marginTop: 24 }]}>Loads on the road</Text>
      <View style={[styles.panel, { backgroundColor: c.card, borderColor: c.border }]}>
        {shipments == null ? (
          <Text style={[styles.body, { color: c.muted }]}>Loading…</Text>
        ) : shipments.length === 0 ? (
          <Text style={[styles.body, { color: c.muted }]}>No loads in the system for your site.</Text>
        ) : (
          <>
            <Text style={[styles.body, { color: c.muted, marginBottom: 12 }]}>
              {tmsStats.total} total · {tmsStats.inTransit} moving · {tmsStats.planned} planned · {tmsStats.delivered}{' '}
              delivered
            </Text>
            {shipments.slice(0, 3).map((s) => (
              <View key={s.id} style={[styles.shipBlock, { borderTopColor: c.border }]}>
                <Text style={[styles.shipId, { color: c.text }]}>{s.shipment_number}</Text>
                <Text style={[styles.body, { color: c.muted }]}>{routeLabel(s)}</Text>
                <Text style={[styles.shipStatus, { color: c.text }]}>
                  {s.status.replace(/_/g, ' ')}
                </Text>
              </View>
            ))}
          </>
        )}
      </View>

      <Pressable
        onPress={onRefresh}
        style={({ pressed }) => [
          styles.refreshBtn,
          { backgroundColor: c.primary, opacity: pressed ? 0.9 : 1 },
        ]}
      >
        <Ionicons name="refresh" size={26} color={c.primaryText} />
        <Text style={[styles.refreshTxt, { color: c.primaryText }]}>Refresh everything</Text>
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  pad: { padding: PAD.screen, paddingBottom: 48 },
  headerRow: { flexDirection: 'row', alignItems: 'flex-start', marginBottom: 20 },
  hero: { fontSize: TYPE.hero, fontWeight: '800' },
  greetLine: { fontSize: TYPE.body, marginTop: 6 },
  liveBlock: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 12,
    borderWidth: 2,
  },
  liveDot: { width: 12, height: 12, borderRadius: 6, backgroundColor: '#22c55e' },
  liveWord: { fontSize: TYPE.label, fontWeight: '800' },
  sectionHdr: { fontSize: TYPE.section, fontWeight: '800', marginBottom: 10, marginTop: 8 },
  sectionHelp: { fontSize: TYPE.small, marginBottom: 10, lineHeight: 22 },
  sectionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 24,
    marginBottom: 10,
  },
  seeAllBtn: { paddingVertical: 12, paddingHorizontal: 8 },
  seeAllTxt: { fontSize: TYPE.body, fontWeight: '800' },
  bigAction: {
    minHeight: HIT.button,
    borderRadius: 16,
    borderWidth: 2,
    paddingHorizontal: 16,
    paddingVertical: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
  },
  bigIconWrap: {
    width: 52,
    height: 52,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  bigActionTitle: { fontSize: TYPE.body, fontWeight: '800' },
  bigActionSub: { fontSize: TYPE.small, marginTop: 4, lineHeight: 20 },
  badge: {
    minWidth: 36,
    height: 36,
    borderRadius: 18,
    paddingHorizontal: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeTxt: { color: '#fff', fontSize: 17, fontWeight: '900' },
  statGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  statCard: {
    width: '47%',
    flexGrow: 1,
    borderRadius: 16,
    borderWidth: 2,
    padding: PAD.card,
    minHeight: 100,
    justifyContent: 'center',
  },
  statNum: { fontSize: TYPE.stat, fontWeight: '900' },
  statLbl: { fontSize: TYPE.label, fontWeight: '700', marginTop: 6, lineHeight: 22 },
  panel: { borderRadius: 16, borderWidth: 2, padding: PAD.card },
  body: { fontSize: TYPE.body, lineHeight: 26 },
  stateRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 16,
    borderBottomWidth: StyleSheet.hairlineWidth,
    minHeight: HIT.row,
  },
  stateName: { fontSize: TYPE.body, fontWeight: '700', flex: 1, paddingRight: 12 },
  stateCount: { fontSize: 32, fontWeight: '900' },
  alarmCard: {
    borderRadius: 16,
    borderWidth: 2,
    padding: PAD.card,
    gap: 10,
  },
  alarmTitle: { fontSize: TYPE.body, fontWeight: '700', lineHeight: 26 },
  alarmMeta: { fontSize: TYPE.small },
  yardGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 },
  yardBox: {
    width: '47%',
    minHeight: 96,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(128,128,128,0.25)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 12,
  },
  yardNum: { fontSize: 36, fontWeight: '900' },
  yardWord: { fontSize: TYPE.label, fontWeight: '700', marginTop: 6, textAlign: 'center' },
  shipBlock: { paddingTop: 14, marginTop: 4, borderTopWidth: StyleSheet.hairlineWidth },
  shipId: { fontSize: TYPE.section, fontWeight: '800' },
  shipStatus: { fontSize: TYPE.label, fontWeight: '800', marginTop: 8, textTransform: 'capitalize' },
  refreshBtn: {
    marginTop: 28,
    minHeight: HIT.button,
    borderRadius: 16,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
  },
  refreshTxt: { fontSize: TYPE.body, fontWeight: '800' },
});
