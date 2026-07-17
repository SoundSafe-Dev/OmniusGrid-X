import React, { useMemo, useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { useAuth } from '../context/AuthContext';
import { useThemeColors } from '../context/ThemeContext';
import { AppButton } from './AppButton';

export type AssignmentPerson = {
  id: string;
  label: string;
  helper?: string;
};

const DEFAULT_PEOPLE: AssignmentPerson[] = [
  { id: 'me', label: 'Me', helper: 'Take ownership now' },
  { id: 'maintenance', label: 'Maintenance lead', helper: 'Mechanical / electrical response' },
  { id: 'quality', label: 'Quality supervisor', helper: 'Inspection or release sign-off' },
  { id: 'operations', label: 'Operations lead', helper: 'Line coordination' },
];

export function selectedPeopleLabel(people: AssignmentPerson[]) {
  return people.map((p) => p.label).join(', ');
}

export function AssignmentPicker({
  visible,
  title = 'Assign to',
  confirmTitle = 'Assign',
  loading = false,
  onCancel,
  onConfirm,
}: {
  visible: boolean;
  title?: string;
  confirmTitle?: string;
  loading?: boolean;
  onCancel: () => void;
  onConfirm: (people: AssignmentPerson[]) => void;
}) {
  const c = useThemeColors();
  const { user } = useAuth();
  const [selected, setSelected] = useState<string[]>(['me']);

  const people = useMemo(() => {
    const meLabel = user?.full_name ? `Me (${user.full_name})` : 'Me';
    return [{ ...DEFAULT_PEOPLE[0], label: meLabel }, ...DEFAULT_PEOPLE.slice(1)];
  }, [user?.full_name]);

  const chosen = people.filter((p) => selected.includes(p.id));

  const toggle = (id: string) => {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onCancel}>
      <View style={styles.backdrop}>
        <View style={[styles.sheet, { backgroundColor: c.card }]}>
          <Text style={[styles.title, { color: c.text }]}>{title}</Text>
          <Text style={[styles.help, { color: c.muted }]}>
            Choose who should own the next step. Multiple people can be selected.
          </Text>

          <View style={{ gap: 10, marginTop: 16 }}>
            {people.map((person) => {
              const on = selected.includes(person.id);
              return (
                <Pressable
                  key={person.id}
                  onPress={() => toggle(person.id)}
                  style={[
                    styles.person,
                    {
                      backgroundColor: on ? c.chip : c.bg,
                      borderColor: on ? c.primary : c.border,
                    },
                  ]}
                >
                  <Ionicons
                    name={on ? 'checkbox' : 'square-outline'}
                    size={28}
                    color={on ? c.primary : c.muted}
                  />
                  <View style={{ flex: 1 }}>
                    <Text style={[styles.personName, { color: c.text }]}>{person.label}</Text>
                    {person.helper ? (
                      <Text style={[styles.personHelp, { color: c.muted }]}>{person.helper}</Text>
                    ) : null}
                  </View>
                </Pressable>
              );
            })}
          </View>

          <View style={styles.actions}>
            <AppButton title="Cancel" variant="secondary" onPress={onCancel} style={{ flex: 1 }} />
            <AppButton
              title={confirmTitle}
              onPress={() => onConfirm(chosen)}
              loading={loading}
              disabled={chosen.length === 0}
              style={{ flex: 1 }}
            />
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#0008', justifyContent: 'flex-end' },
  sheet: { padding: 20, borderTopLeftRadius: 20, borderTopRightRadius: 20 },
  title: { fontSize: 22, fontWeight: '900' },
  help: { fontSize: 15, lineHeight: 22, marginTop: 6 },
  person: {
    minHeight: 68,
    borderWidth: 2,
    borderRadius: 16,
    padding: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  personName: { fontSize: 17, fontWeight: '800' },
  personHelp: { fontSize: 14, lineHeight: 20, marginTop: 2 },
  actions: { flexDirection: 'row', gap: 10, marginTop: 18 },
});
