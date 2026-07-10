import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import type { StackScreenProps } from '@react-navigation/stack';
import { useNavigation } from '@react-navigation/native';
import type { AppStackParamList } from '../navigation/types';
import { useThemeColors } from '../context/ThemeContext';
import { useToast } from '../context/ToastContext';
import { AppButton } from '../components/AppButton';
import { Chip } from '../components/Chip';
import * as api from '../api/omniusApi';
import type { Asset, AssetStatus, YardTrailer } from '../api/types';
import { useDemoLive } from '../demo/DemoLiveProvider';

type Props = StackScreenProps<AppStackParamList, 'AssetDetail'>;

export function AssetDetailScreen({ route }: Props) {
  const { kind, id } = route.params;
  const { seq: demoLiveSeq } = useDemoLive();
  const c = useThemeColors();
  const toast = useToast();
  const nav = useNavigation<any>();
  const [asset, setAsset] = useState<Asset | null>(null);
  const [status, setStatus] = useState<AssetStatus | null>(null);
  const [trailer, setTrailer] = useState<YardTrailer | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    if (kind === 'asset') {
      const [a, s] = await Promise.all([api.fetchAsset(id), api.fetchAssetStatus(id).catch(() => null)]);
      setAsset(a);
      setStatus(s);
    } else {
      const t = await api.fetchYardTrailer(id);
      setTrailer(t);
    }
  };

  React.useEffect(() => {
    void load();
  }, [kind, id, demoLiveSeq]);

  const refresh = async () => {
    setBusy(true);
    try {
      await load();
      toast.show('Status updated');
    } catch {
      toast.error('Could not refresh');
    } finally {
      setBusy(false);
    }
  };

  const setPackml = async (state: string) => {
    if (!asset) return;
    setBusy(true);
    try {
      const a = await api.updateAsset(asset.id, { current_packml_state: state });
      setAsset(a);
      toast.show('Status updated');
    } catch {
      toast.error('Could not update');
    } finally {
      setBusy(false);
    }
  };

  const setTrailerStatus = async (statusVal: string) => {
    if (!trailer) return;
    setBusy(true);
    try {
      const t = await api.updateYardTrailer(trailer.id, { status: statusVal });
      setTrailer(t);
      toast.show('Trailer updated');
    } catch {
      toast.error('Could not update');
    } finally {
      setBusy(false);
    }
  };

  if (kind === 'trailer') {
    if (!trailer) {
      return (
        <View style={[styles.c, { backgroundColor: c.bg }]}>
          <Text style={{ color: c.muted }}>Loading…</Text>
        </View>
      );
    }
    return (
      <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={styles.pad}>
        <Text style={[styles.title, { color: c.text }]}>{trailer.trailer_number}</Text>
        <Chip label={trailer.status} />
        <Text style={[styles.p, { color: c.muted, marginTop: 12 }]}>Location: {trailer.yard_location || '—'}</Text>
        <AppButton title="Refresh status" onPress={refresh} loading={busy} style={{ marginTop: 20 }} />
        <Text style={[styles.h, { color: c.text }]}>Quick status</Text>
        <AppButton title="Mark checked in" variant="secondary" onPress={() => setTrailerStatus('checked_in')} style={styles.gap} />
        <AppButton title="Mark yard" variant="secondary" onPress={() => setTrailerStatus('yard')} style={styles.gap} />
        <AppButton title="Mark docked" variant="secondary" onPress={() => setTrailerStatus('docked')} style={styles.gap} />
        <AppButton title="Mark checked out" variant="secondary" onPress={() => setTrailerStatus('checked_out')} style={styles.gap} />
        <AppButton title="Alert admin" variant="ghost" onPress={() => nav.navigate('ContactAdminApp')} style={styles.gap} />
      </ScrollView>
    );
  }

  if (!asset) {
    return (
      <View style={[styles.c, { backgroundColor: c.bg }]}>
        <Text style={{ color: c.muted }}>Loading…</Text>
      </View>
    );
  }

  return (
    <ScrollView style={{ backgroundColor: c.bg }} contentContainerStyle={styles.pad}>
      <Text style={[styles.title, { color: c.text }]}>{asset.name}</Text>
      <View style={{ flexDirection: 'row', gap: 8, marginTop: 8 }}>
        <Chip label="Machine" />
        <Chip label={status?.current_packml_state ?? asset.current_packml_state} />
      </View>
      <Text style={[styles.p, { color: c.muted, marginTop: 12 }]}>
        Last seen: {status?.last_seen ? new Date(status.last_seen).toLocaleString() : '—'}
      </Text>
      <AppButton title="Refresh status" onPress={refresh} loading={busy} style={{ marginTop: 20 }} />
      <Text style={[styles.h, { color: c.text }]}>PackML (supervisor)</Text>
      <AppButton title="Mark Idle" variant="secondary" onPress={() => setPackml('Idle')} style={styles.gap} />
      <AppButton title="Mark Execute" variant="secondary" onPress={() => setPackml('Execute')} style={styles.gap} />
      <AppButton title="Mark Complete" variant="secondary" onPress={() => setPackml('Complete')} style={styles.gap} />
      <AppButton title="Alert admin" variant="ghost" onPress={() => nav.navigate('ContactAdminApp')} style={styles.gap} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  c: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  pad: { padding: 16, paddingBottom: 40 },
  title: { fontSize: 22, fontWeight: '800' },
  p: { fontSize: 16 },
  h: { fontSize: 18, fontWeight: '800', marginTop: 20 },
  gap: { marginTop: 10 },
});
