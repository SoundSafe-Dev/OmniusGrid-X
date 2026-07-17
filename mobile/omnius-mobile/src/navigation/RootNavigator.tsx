import React from 'react';
import { ActivityIndicator, View } from 'react-native';
import { NavigationContainer, DefaultTheme, DarkTheme, Theme } from '@react-navigation/native';
import { createStackNavigator } from '@react-navigation/stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { Ionicons } from '@expo/vector-icons';

import { useAuth } from '../context/AuthContext';
import { useTheme } from '../context/ThemeContext';
import type { AuthStackParamList, MainTabParamList, AppStackParamList } from './types';

import { LoginScreen } from '../screens/LoginScreen';
import { ForgotPasswordScreen } from '../screens/ForgotPasswordScreen';
import { ContactAdminScreen } from '../screens/ContactAdminScreen';
import { HomeScreen } from '../screens/HomeScreen';
import { TasksListScreen } from '../screens/TasksListScreen';
import { AlertsListScreen } from '../screens/AlertsListScreen';
import { AssetsOverviewScreen } from '../screens/AssetsOverviewScreen';
import { MoreScreen } from '../screens/MoreScreen';
import { TaskDetailScreen } from '../screens/TaskDetailScreen';
import { AlertDetailScreen } from '../screens/AlertDetailScreen';
import { AssetDetailScreen } from '../screens/AssetDetailScreen';

/** JS stack avoids `react-native-screens` native views (RNSScreen*), which can double-register under Expo Go. */
const AuthStack = createStackNavigator<AuthStackParamList>();
const AppStack = createStackNavigator<AppStackParamList>();
const Tabs = createBottomTabNavigator<MainTabParamList>();

function MainTabs() {
  const { colors } = useTheme();
  return (
    <Tabs.Navigator
      screenOptions={{
        headerTitleStyle: { fontWeight: '700', fontSize: 18 },
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.muted,
        tabBarStyle: { minHeight: 64, paddingBottom: 10, paddingTop: 8 },
        tabBarLabelStyle: { fontSize: 14, fontWeight: '800' },
      }}
    >
      <Tabs.Screen
        name="Home"
        component={HomeScreen}
        options={{
          title: 'Dashboard',
          tabBarLabel: 'Home',
          tabBarIcon: ({ color, size }) => <Ionicons name="home" color={color} size={size + 4} />,
        }}
      />
      <Tabs.Screen
        name="TasksTab"
        component={TasksListScreen}
        options={{
          title: 'Tasks',
          headerShown: false,
          tabBarIcon: ({ color, size }) => <Ionicons name="list" color={color} size={size + 4} />,
        }}
      />
      <Tabs.Screen
        name="AlertsTab"
        component={AlertsListScreen}
        options={{
          title: 'Alerts',
          headerShown: false,
          tabBarIcon: ({ color, size }) => <Ionicons name="warning" color={color} size={size + 4} />,
        }}
      />
      <Tabs.Screen
        name="AssetsTab"
        component={AssetsOverviewScreen}
        options={{
          title: 'Assets',
          headerShown: false,
          tabBarIcon: ({ color, size }) => <Ionicons name="cube" color={color} size={size + 4} />,
        }}
      />
      <Tabs.Screen
        name="More"
        component={MoreScreen}
        options={{
          title: 'More',
          tabBarIcon: ({ color, size }) => <Ionicons name="menu" color={color} size={size + 4} />,
        }}
      />
    </Tabs.Navigator>
  );
}

function buildNavTheme(colors: ReturnType<typeof useTheme>['colors'], dark: boolean): Theme {
  const base = dark ? DarkTheme : DefaultTheme;
  return {
    ...base,
    colors: {
      ...base.colors,
      primary: colors.primary,
      background: colors.bg,
      card: colors.card,
      text: colors.text,
      border: colors.border,
      notification: colors.danger,
    },
  };
}

export function RootNavigator() {
  const { user, ready } = useAuth();
  const { colors, isDark } = useTheme();
  const navTheme = buildNavTheme(colors, isDark);

  const stackScreenOptions = {
    headerStyle: { backgroundColor: colors.card },
    headerTintColor: colors.primary,
    headerTitleStyle: { fontWeight: '700' as const, fontSize: 18, color: colors.text },
    cardStyle: { backgroundColor: colors.bg },
  };

  if (!ready) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.bg }}>
        <ActivityIndicator size="large" color={colors.primary} />
      </View>
    );
  }

  return (
    <NavigationContainer theme={navTheme}>
      {!user ? (
        <AuthStack.Navigator screenOptions={stackScreenOptions}>
          <AuthStack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
          <AuthStack.Screen name="ForgotPassword" component={ForgotPasswordScreen} options={{ title: 'Forgot password' }} />
          <AuthStack.Screen name="ContactAdmin" component={ContactAdminScreen} options={{ title: 'Contact admin' }} />
        </AuthStack.Navigator>
      ) : (
        <AppStack.Navigator screenOptions={stackScreenOptions}>
          <AppStack.Screen name="MainTabs" component={MainTabs} options={{ headerShown: false }} />
          <AppStack.Screen name="TaskDetail" component={TaskDetailScreen} options={{ title: 'Task' }} />
          <AppStack.Screen name="AlertDetail" component={AlertDetailScreen} options={{ title: 'Alert' }} />
          <AppStack.Screen name="AssetDetail" component={AssetDetailScreen} options={{ title: 'Asset' }} />
          <AppStack.Screen name="ContactAdminApp" component={ContactAdminScreen} options={{ title: 'Contact admin' }} />
        </AppStack.Navigator>
      )}
    </NavigationContainer>
  );
}
