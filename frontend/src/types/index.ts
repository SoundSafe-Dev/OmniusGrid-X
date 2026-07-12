export * from './auth';
export * from './asset';
export * from './alarm';
export * from './telemetry';
export * from './engine';
export * from './common';
export * from './logistics';
export * from './fleet';

// Both common.ts (interface { label; hours }) and logistics.ts (string union)
// declare a TimeRange. The logistics union is the canonical API-facing one;
// import the legacy interface directly from './common' where needed.
export type { TimeRange } from './logistics';
