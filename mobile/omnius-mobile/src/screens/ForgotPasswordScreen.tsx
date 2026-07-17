import React from 'react';
import { View, Text, StyleSheet, Linking } from 'react-native';
import type { StackScreenProps } from '@react-navigation/stack';
import { SUPPORT_EMAIL } from '../config';
import { useThemeColors } from '../context/ThemeContext';
import { AppButton } from '../components/AppButton';
import type { AuthStackParamList } from '../navigation/types';

type Props = StackScreenProps<AuthStackParamList, 'ForgotPassword'>;

export function ForgotPasswordScreen(_props: Props) {
  const c = useThemeColors();
  return (
    <View style={[styles.wrap, { backgroundColor: c.bg }]}>
      <Text style={[styles.body, { color: c.text }]}>
        Password reset is not available in the app yet. Contact your IT administrator or operations lead to reset
        your account.
      </Text>
      <AppButton
        title="Email IT"
        variant="secondary"
        onPress={() => Linking.openURL(`mailto:${SUPPORT_EMAIL}?subject=Omnius%20Grid%20password%20reset`)}
        style={{ marginTop: 20 }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, padding: 20, paddingTop: 24 },
  body: { fontSize: 17, lineHeight: 24 },
});
