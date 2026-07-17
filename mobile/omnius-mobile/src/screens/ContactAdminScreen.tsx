import React, { useState } from 'react';
import { View, Text, TextInput, StyleSheet } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useThemeColors } from '../context/ThemeContext';
import { useToast } from '../context/ToastContext';
import { AppButton } from '../components/AppButton';

const KEY = 'omnius_mock_admin_messages';

type Props = {
  navigation: { goBack: () => void };
};

export function ContactAdminScreen({ navigation }: Props) {
  const c = useThemeColors();
  const toast = useToast();
  const [body, setBody] = useState('');
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (!body.trim()) {
      toast.error('Please enter a message');
      return;
    }
    setSaving(true);
    try {
      const prev = await AsyncStorage.getItem(KEY);
      const list = prev ? (JSON.parse(prev) as unknown[]) : [];
      list.push({
        body: body.trim(),
        at: new Date().toISOString(),
      });
      await AsyncStorage.setItem(KEY, JSON.stringify(list));
      toast.show('Message saved locally');
      setBody('');
      navigation.goBack();
    } catch {
      toast.error('Could not save. Try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <View style={[styles.wrap, { backgroundColor: c.bg }]}>
      <Text style={[styles.hint, { color: c.muted }]}>
        There is no admin messaging API yet. Your note is stored on this device for demo purposes.
      </Text>
      <TextInput
        value={body}
        onChangeText={setBody}
        multiline
        placeholder="What do you need from admin?"
        placeholderTextColor={c.muted}
        style={[styles.area, { color: c.text, borderColor: c.border, backgroundColor: c.card }]}
      />
      <AppButton title="Save note" onPress={save} loading={saving} style={{ marginTop: 16 }} />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, padding: 20 },
  hint: { fontSize: 15, marginBottom: 12, lineHeight: 22 },
  area: {
    minHeight: 160,
    borderWidth: 2,
    borderRadius: 12,
    padding: 14,
    fontSize: 17,
    textAlignVertical: 'top',
  },
});
