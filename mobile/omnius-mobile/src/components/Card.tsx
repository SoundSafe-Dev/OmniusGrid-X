import React from 'react';
import { StyleSheet, Text, View, ViewStyle } from 'react-native';
import { useThemeColors } from '../context/ThemeContext';

export function Card({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  const c = useThemeColors();
  return <View style={[styles.card, { backgroundColor: c.card, borderColor: c.border }, style]}>{children}</View>;
}

export function CardTitle({ children }: { children: React.ReactNode }) {
  const c = useThemeColors();
  return <Text style={[styles.title, { color: c.text }]}>{children}</Text>;
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 14,
    borderWidth: 1,
    padding: 16,
    marginBottom: 12,
  },
  title: { fontSize: 18, fontWeight: '800', marginBottom: 8 },
});
