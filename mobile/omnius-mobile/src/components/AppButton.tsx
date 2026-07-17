import React from 'react';
import { Pressable, StyleSheet, Text, ViewStyle, ActivityIndicator } from 'react-native';
import { useThemeColors } from '../context/ThemeContext';

type Props = {
  title: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  disabled?: boolean;
  loading?: boolean;
  style?: ViewStyle;
};

export function AppButton({
  title,
  onPress,
  variant = 'primary',
  disabled,
  loading,
  style,
}: Props) {
  const c = useThemeColors();
  const bg =
    variant === 'primary'
      ? c.primary
      : variant === 'danger'
        ? c.danger
        : variant === 'secondary'
          ? c.card
          : 'transparent';
  const color =
    variant === 'primary' || variant === 'danger'
      ? c.primaryText
      : variant === 'secondary'
        ? c.text
        : c.primary;
  const border =
    variant === 'secondary' ? { borderWidth: 2, borderColor: c.border } : variant === 'ghost' ? {} : {};

  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.btn,
        { backgroundColor: bg, opacity: pressed ? 0.88 : disabled ? 0.45 : 1 },
        border,
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color={color} />
      ) : (
        <Text style={[styles.label, { color }]}>{title}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: {
    minHeight: 58,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 20,
  },
  label: { fontSize: 19, fontWeight: '800' },
});
