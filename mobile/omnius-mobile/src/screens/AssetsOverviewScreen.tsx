import React, { useCallback, useMemo, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TextInput,
  Pressable,
  RefreshControl,
} from 'react-native';
import { useNavigation, useRoute, RouteProp } from '@react-navigation/native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '../context/AuthContext';
import { useThemeColors } from '../context/ThemeContext';
import { useToast } from '../context/ToastContext';
import type { Asset, YardTrailer } from '../api/types';
import * as api from '../api/omniusApi';
import type { MainTabParamList } from '../navigation/types';
import { useDemoLive } from '../demo/DemoLiveProvider';
import { formatAlarmDateTime } from '../utils/format';
import { HIT, PAD, TYPE } from '../theme/supervisorTouch';

type TopTab = 'trucks' | 'machines' | 'other';

type R = RouteProp<MainTabParamList, 'AssetsTab'>;

export function AssetsOverviewScreen() {
  const c = useThemeColors();
  const insets = useSafeAreaInsets();
  const { seq: demoLiveSeq } = useDemoLive();
  const navigation = useNavigation<any>();
  const route = useRoute<R>();
  const { user } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState<TopTab>('machines');
  const [q, setQ] = useState('');
  const [assets, setAssets] = useState<Asset[]>([]);
  const [trailers, setTrailers] = useState<YardTrailer[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  React.useEffect(() => {
    const t = route.params?.tab;
    if (t) {
      setTab(t === 'trucks' ? 'trucks' : 'machines');
      navigation.setParams({ tab: undefined });
    }
  }, [route.params?.tab, navigation]);

  const load = useCallback(async () => {
    if (!user?.organization_id) return;
    try {
      const [a, tr] = await Promise.all([
        api.fetchAssetsList(user.organization_id),
        api.fetchYardTrailers(user.organization_id).catch(() => [] as YardTrailer[]),
      ]);
      setAssets(a);
      setTrailers(tr);
    } catch {
      toast.error('Could not load assets');
    }
  }, [user?.organization_id, toast, demoLiveSeq]);

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

  const filteredAssets = useMemo(() => {
    const qq = q.trim().toLowerCase();
    return assets.filter((x) => !qq || x.name.toLowerCase().includes(qq) || x.id.toLowerCase().includes(qq));
  }, [assets, q]);

  const filteredTrailers = useMemo(() => {
    const qq = q.trim().toLowerCase();
    return trailers.filter((x) => !qq || x.trailer_number.toLowerCase().includes(qq) || x.id.toLowerCase().includes(qq));
  }, [trailers, q]);

  const chips: { key: TopTab; label: string }[] = [
    { key: 'trucks', label: 'Trailers' },
    { key: 'machines', label: 'Equipment' },
    { key: 'other', label: 'Other' },
  ];

  return (
    <View style={{ flex: 1, backgroundColor: c.bg }}>
      <View style={[styles.tabs, { borderBottomColor: c.border, paddingTop: insets.top }]}>
        {chips.map((x) => {
          const on = tab === x.key;
          return (
            <Pressable
              key={x.key}
              onPress={() => setTab(x.key)}
              style={[styles.tab, on && { borderBottomWidth: 3, borderBottomColor: c.primary }]}
            >
              <Text style={[styles.tabTxt, { color: on ? c.primary : c.muted }]}>{x.label}</Text>
            </Pressable>
          );
        })}
      </View>

      <TextInput
        value={q}
        onChangeText={setQ}
        placeholder="Search name or ID"
        placeholderTextColor={c.muted}
        style={[styles.search, { color: c.text, borderColor: c.border, backgroundColor: c.card }]}
      />

      {(tab === 'trucks' || tab === 'machines') && (
        <View style={styles.subHead}>
          <Text style={[styles.assetsTitle, { color: c.text }]}>Assets</Text>
          <Text style={[styles.totalLbl, { color: c.muted }]}>
            {tab === 'trucks' ? `${filteredTrailers.length} total` : `${filteredAssets.length} total`}
          </Text>
        </View>
      )}

      {tab === 'trucks' ? (
        <FlatList
          data={filteredTrailers}
          keyExtractor={(x) => x.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
          contentContainerStyle={{ padding: PAD.screen, paddingBottom: 100 }}
          ListEmptyComponent={<Text style={{ color: c.muted, textAlign: 'center', marginTop: 24 }}>No trailers</Text>}
          renderItem={({ item }) => (
            <Pressable
              onPress={() => navigation.navigate('AssetDetail', { kind: 'trailer', id: item.id })}
              style={[styles.row, { backgroundColor: c.card, borderColor: c.border }]}
            >
              <View style={styles.rowTop}>
                <View style={[styles.cube, { borderColor: c.muted }]} />
                <View style={{ flex: 1 }}>
                  <Text style={[styles.name, { color: c.text }]}>{item.trailer_number}</Text>
                  <Text style={[styles.sub, { color: c.muted }]}>{item.yard_location || 'Yard'}</Text>
                  <Text style={[styles.stateLbl, { color: c.muted }]}>State</Text>
                  <Text style={[styles.stateVal, { color: c.text }]}>{item.status}</Text>
                </View>
                <View style={[styles.statusDot, { backgroundColor: c.muted }]} />
              </View>
              <Text style={[styles.detailsLink, { color: c.primary }]}>Open details {'>'}</Text>
            </Pressable>
          )}
        />
      ) : (
        <FlatList
          data={filteredAssets}
          keyExtractor={(x) => x.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
          contentContainerStyle={{ padding: PAD.screen, paddingBottom: 100 }}
          ListHeaderComponent={
            tab === 'other' ? (
              <Text style={{ color: c.muted, marginBottom: 12, fontSize: 15 }}>
                Other plant assets use the same catalog until types are split in the API.
              </Text>
            ) : null
          }
          ListEmptyComponent={<Text style={{ color: c.muted, textAlign: 'center', marginTop: 24 }}>No assets</Text>}
          renderItem={({ item }) => (
            <Pressable
              onPress={() => navigation.navigate('AssetDetail', { kind: 'asset', id: item.id })}
              style={[styles.row, { backgroundColor: c.card, borderColor: c.border }]}
            >
              <View style={styles.rowTop}>
                <View style={[styles.cube, { borderColor: c.muted }]} />
                <View style={{ flex: 1 }}>
                  <Text style={[styles.name, { color: c.text }]}>{item.name}</Text>
                  <Text style={[styles.sub, { color: c.muted }]} numberOfLines={1}>
                    PackML · {item.current_packml_state}
                  </Text>
                  <Text style={[styles.stateLbl, { color: c.muted }]}>State</Text>
                  <Text style={[styles.stateVal, { color: c.text }]}>
                    {item.is_active ? 'Online' : 'Offline'}
                    {item.last_seen ? ` · seen ${formatAlarmDateTime(item.last_seen)}` : ''}
                  </Text>
                </View>
                <View
                  style={[
                    styles.statusDot,
                    { backgroundColor: item.is_active ? '#22c55e' : c.muted },
                  ]}
                />
              </View>
              <Text style={[styles.detailsLink, { color: c.primary }]}>Open details {'>'}</Text>
            </Pressable>
          )}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  tabs: { flexDirection: 'row', borderBottomWidth: 2 },
  tab: { flex: 1, minHeight: HIT.tab, alignItems: 'center', justifyContent: 'center', paddingVertical: 8 },
  tabTxt: { fontSize: TYPE.label, fontWeight: '800' },
  subHead: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: PAD.screen,
    marginBottom: 6,
  },
  assetsTitle: { fontSize: TYPE.title, fontWeight: '900' },
  totalLbl: { fontSize: TYPE.body, fontWeight: '800' },
  search: {
    marginHorizontal: PAD.screen,
    marginTop: 8,
    marginBottom: 8,
    borderWidth: 2,
    borderRadius: 14,
    minHeight: HIT.button,
    paddingHorizontal: 16,
    fontSize: TYPE.body,
  },
  row: {
    borderWidth: 2,
    borderRadius: 16,
    padding: PAD.card,
    marginBottom: 14,
  },
  rowTop: { flexDirection: 'row', alignItems: 'flex-start', gap: 14 },
  cube: {
    width: 36,
    height: 36,
    borderWidth: 2,
    borderRadius: 8,
    marginTop: 2,
  },
  statusDot: { width: 14, height: 14, borderRadius: 7, marginTop: 8 },
  stateLbl: { fontSize: TYPE.small, fontWeight: '800', marginTop: 12, textTransform: 'uppercase' },
  stateVal: { fontSize: TYPE.body, fontWeight: '700', marginTop: 6, lineHeight: 26 },
  detailsLink: {
    fontSize: TYPE.body,
    fontWeight: '800',
    textAlign: 'right',
    marginTop: 16,
    paddingVertical: 12,
  },
  name: { fontSize: TYPE.section, fontWeight: '900' },
  sub: { fontSize: TYPE.body, marginTop: 6, lineHeight: 24 },
});
