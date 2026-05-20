import React from 'react';
import { StatusBar } from 'expo-status-bar';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { ThemeProvider } from './src/context/ThemeContext';
import { AuthProvider } from './src/context/AuthContext';
import { ToastProvider } from './src/context/ToastContext';
import { RootNavigator } from './src/navigation/RootNavigator';
import { useTheme } from './src/context/ThemeContext';
import { DemoLiveProvider } from './src/demo/DemoLiveProvider';
import { AssistantLauncher } from './src/components/AssistantLauncher';

function Status() {
  const { isDark } = useTheme();
  return <StatusBar style={isDark ? 'light' : 'dark'} />;
}

export default function App() {
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <ThemeProvider>
          <DemoLiveProvider>
            <AuthProvider>
              <ToastProvider>
                <Status />
                <RootNavigator />
                <AssistantLauncher />
              </ToastProvider>
            </AuthProvider>
          </DemoLiveProvider>
        </ThemeProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
