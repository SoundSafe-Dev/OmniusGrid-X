import { NavigatorScreenParams } from '@react-navigation/native';

export type TaskSegment = 'new' | 'in_progress' | 'completed';

export type MainTabParamList = {
  Home: { tasksSegment?: TaskSegment } | undefined;
  TasksTab: { segment?: TaskSegment } | undefined;
  AlertsTab: { filter?: 'active' | 'ack' | 'resolved' } | undefined;
  AssetsTab: { tab?: 'trucks' | 'machines' } | undefined;
  More: undefined;
};

export type AuthStackParamList = {
  Login: undefined;
  ForgotPassword: undefined;
  ContactAdmin: undefined;
};

export type AppStackParamList = {
  MainTabs: NavigatorScreenParams<MainTabParamList> | undefined;
  TaskDetail: { taskId: string };
  AlertDetail: { alarmId: string };
  AssetDetail: { kind: 'asset' | 'trailer'; id: string };
  ContactAdminApp: undefined;
};

/** @deprecated use AuthStackParamList / AppStackParamList */
export type RootStackParamList = AuthStackParamList & AppStackParamList;
