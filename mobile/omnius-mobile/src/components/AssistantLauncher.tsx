import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useAuth } from '../context/AuthContext';
import { useThemeColors } from '../context/ThemeContext';
import { useToast } from '../context/ToastContext';

export function AssistantLauncher() {
  const c = useThemeColors();
  const toast = useToast();
  const { user } = useAuth();
  const insets = useSafeAreaInsets();

  if (!user) return null;

  return (
    <View pointerEvents="box-none" style={StyleSheet.absoluteFill}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Open AI assistant"
        onPress={() => toast.show('AI assistant coming soon')}
        style={({ pressed }) => [
          styles.wrap,
          {
            bottom: Math.max(insets.bottom + 84, 96),
            backgroundColor: c.primary,
            shadowColor: c.text,
            opacity: pressed ? 0.9 : 1,
          },
        ]}
      >
        <View style={styles.spark}>
          <Ionicons name="sparkles" size={17} color={c.primary} />
        </View>
        <View>
          <Text style={styles.kicker}>Ask</Text>
          <Text style={styles.label}>AI</Text>
        </View>
        <Ionicons name="mic" size={18} color={c.primaryText} />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    position: 'absolute',
    right: 16,
    zIndex: 50,
    minHeight: 58,
    borderRadius: 29,
    paddingLeft: 9,
    paddingRight: 14,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 9,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.22,
    shadowRadius: 14,
    elevation: 8,
  },
  spark: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#fff',
  },
  kicker: {
    color: '#fff',
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.4,
    textTransform: 'uppercase',
  },
  label: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '900',
    marginTop: -2,
  },
});
