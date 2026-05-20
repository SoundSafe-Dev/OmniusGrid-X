# Omnius Grid — Mobile (Android-first)

This directory holds **mobile-specific** material: the **Expo supervisor app**, API integration maps, demo personas, and fixtures. It is intentionally separate from `frontend/`, which remains the web console.

## Supervisor app (`omnius-mobile/`)

Expo SDK 54 + React Native + TypeScript. Screens: **Login** (forgot password, contact admin), **Home**, **Tasks** (list + detail), **Alerts** (list + detail), **Assets** (trucks / machines / other + detail), **More** (profile, theme, help).

```bash
cd mobile/omnius-mobile
npm install
npx expo start
# then press a for Android emulator / device
```

Set the API host with env (optional). Defaults: **Android emulator** → `http://10.0.2.2:8000`, **iOS simulator** → `http://localhost:8000`.

```bash
EXPO_PUBLIC_API_URL=http://192.168.1.10:8000 npx expo start
```

Ensure the backend CORS settings allow your dev host if you use Expo Web.

Navigation uses **`@react-navigation/stack`** (JS transitions) instead of **native stack**, so `react-native-screens` view managers are not registered twice under **Expo Go** (avoids `Tried to register two views with the same name RNSScreen`).

**Expo Go:** keep `react-native-screens` on the version range from `expo/bundledNativeModules.json` (SDK 54 uses `~4.16.0`). Installing a newer JS-only version (e.g. `4.25.x`) while Expo Go still ships older native code causes `expected dynamic type 'boolean', but had type 'string'` at startup. Use a dev build if you need a newer `react-native-screens`.

## Contents

| Path | Purpose |
|------|---------|
| `omnius-mobile/` | Full Expo app (navigation, screens, API client). |
| `docs/BACKEND_ENDPOINT_MAP.md` | Screen-by-screen mapping to FastAPI routes, auth, query params, and gaps (mock data). |
| `fixtures/omnius-supervisor.json` | Demo supervisor persona **Omnius** (profile fields, suggested registration payload, org id). |
| `fixtures/mock-contact-admin.json` | Example local-only payload shape for “Contact admin” / “Alert admin” until a messaging API exists. |

## Base URL

Configure the app to use the same API host as the web app (for example `http://10.0.2.2:8000` from the Android emulator, or your deployed host). All documented paths are relative to that origin.

## Auth

- Login uses **OAuth2 password form** (`application/x-www-form-urlencoded`), not JSON. See the endpoint map for field names (`username` = email).
- Subsequent calls use `Authorization: Bearer <access_token>`.

## OpenAPI

When the backend is running, `GET /docs` and `GET /openapi.json` are the source of truth for request/response models. The markdown map may call out **duplicate path segments** (e.g. `/api/v1/yard/yard/...`) that come from nested `APIRouter` prefixes in code—verify on your branch before shipping clients.
