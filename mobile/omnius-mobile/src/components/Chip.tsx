import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useThemeColors } from '../context/ThemeContext';

export function Chip({
  label,
  tone = 'default',
  size = 'default',
}: {
  label: string;
  tone?: 'default' | 'danger' | 'warn' | 'ok';
  size?: 'default' | 'touch';
}) {
  const c = useThemeColors();
  const bg =
    tone === 'danger' ? '#FEE2E2' : tone === 'warn' ? '#FEF3C7' : tone === 'ok' ? '#D1FAE5' : c.chip;
  const fg =
    tone === 'danger' ? '#991B1B' : tone === 'warn' ? '#92400E' : tone === 'ok' ? '#065F46' : c.primary;
  const padV = size === 'touch' ? 8 : 4;
  const padH = size === 'touch' ? 14 : 10;
  const fontSize = size === 'touch' ? 16 : 13;
  return (
    <View style={[styles.wrap, { backgroundColor: bg, paddingVertical: padV, paddingHorizontal: padH }]}>
      <Text style={[styles.txt, { color: fg, fontSize }]} numberOfLines={1}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { borderRadius: 999, maxWidth: 220, alignSelf: 'flex-start' },
  txt: { fontWeight: '700' },
});
