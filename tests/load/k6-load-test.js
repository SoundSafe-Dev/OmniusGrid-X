// OmniusGrid Load Test with k6
// Target: 1000 concurrent users, 10k req/sec

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');

// Test configuration
export const options = {
  stages: [
    { duration: '2m', target: 100 },   // Ramp up to 100 users
    { duration: '5m', target: 500 },   // Ramp up to 500 users
    { duration: '5m', target: 1000 },  // Ramp up to 1000 users
    { duration: '10m', target: 1000 }, // Stay at 1000 users
    { duration: '5m', target: 500 },   // Ramp down to 500 users
    { duration: '2m', target: 0 },     // Ramp down to 0
  ],
  thresholds: {
    http_req_duration: ['p(95)<500', 'p(99)<1000'], // 95% under 500ms, 99% under 1s
    http_req_failed: ['rate<0.01'], // Error rate < 1%
    errors: ['rate<0.01'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8002';
const API_KEY = __ENV.API_KEY || '';

// Helper function to make authenticated requests
function makeRequest(method, endpoint, data = null) {
  const headers = {
    'Content-Type': 'application/json',
  };
  
  if (API_KEY) {
    headers['X-API-Key'] = API_KEY;
  } else {
    // Token via env (-e API_TOKEN=...): hardened targets reject dev-token,
    // which is only valid where ALLOW_DEV_TOKEN=true (dev/CI).
    headers['Authorization'] = `Bearer ${__ENV.API_TOKEN || 'dev-token'}`;
  }
  
  const params = {
    headers: headers,
  };
  
  if (method === 'POST' || method === 'PUT' || method === 'PATCH') {
    return http[method.toLowerCase()](`${BASE_URL}${endpoint}`, JSON.stringify(data), params);
  } else {
    return http[method.toLowerCase()](`${BASE_URL}${endpoint}`, params);
  }
}

// Test scenarios
export default function () {
  // Scenario 1: Health check (lightweight)
  let healthRes = makeRequest('GET', '/health');
  check(healthRes, {
    'health check status 200': (r) => r.status === 200,
  }) || errorRate.add(1);
  
  sleep(1);
  
  // Scenario 2: Get assets (read-heavy)
  let assetsRes = makeRequest('GET', '/api/v1/assets');
  check(assetsRes, {
    'assets status 200': (r) => r.status === 200,
    'assets has items': (r) => JSON.parse(r.body).items !== undefined,
  }) || errorRate.add(1);
  
  sleep(1);
  
  // Scenario 3: Get telemetry (read-heavy)
  let telemetryRes = makeRequest('GET', '/api/v1/telemetry');
  check(telemetryRes, {
    'telemetry status 200': (r) => r.status === 200,
  }) || errorRate.add(1);
  
  sleep(1);
  
  // Scenario 4: Get alarms (read-heavy)
  let alarmsRes = makeRequest('GET', '/api/v1/alarms');
  check(alarmsRes, {
    'alarms status 200': (r) => r.status === 200,
  }) || errorRate.add(1);
  
  sleep(1);
  
  // Scenario 5: Get dashboard data (read-heavy)
  let dashboardRes = makeRequest('GET', '/api/v1/dashboard');
  check(dashboardRes, {
    'dashboard status 200': (r) => r.status === 200,
  }) || errorRate.add(1);
  
  sleep(1);
  
  // Scenario 6: Get kanban tasks (read-heavy)
  let kanbanRes = makeRequest('GET', '/api/v1/kanban/tasks');
  check(kanbanRes, {
    'kanban status 200': (r) => r.status === 200,
  }) || errorRate.add(1);
  
  sleep(1);
  
  // Scenario 7: Get user info (read-heavy)
  let userRes = makeRequest('GET', '/api/v1/auth/me');
  check(userRes, {
    'user info status 200': (r) => r.status === 200,
    'user has email': (r) => JSON.parse(r.body).email !== undefined,
  }) || errorRate.add(1);
  
  sleep(1);
  
  // Scenario 8: Get registries (read-heavy)
  let registriesRes = makeRequest('GET', '/api/v1/registries');
  check(registriesRes, {
    'registries status 200': (r) => r.status === 200,
  }) || errorRate.add(1);
  
  sleep(1);
}

// Alternative test: Write operations
export function handleWriteOperations() {
  // Create a test asset
  const assetData = {
    name: `Test Asset ${__VU}`,
    type: 'machine',
    location: 'Test Location',
    status: 'active',
  };
  
  let createRes = makeRequest('POST', '/api/v1/assets', assetData);
  check(createRes, {
    'create asset status 201': (r) => r.status === 201,
  }) || errorRate.add(1);
  
  if (createRes.status === 201) {
    const assetId = JSON.parse(createRes.body).id;
    
    sleep(1);
    
    // Update the asset
    const updateData = {
      status: 'maintenance',
    };
    
    let updateRes = makeRequest('PUT', `/api/v1/assets/${assetId}`, updateData);
    check(updateRes, {
      'update asset status 200': (r) => r.status === 200,
    }) || errorRate.add(1);
    
    sleep(1);
    
    // Delete the asset
    let deleteRes = makeRequest('DELETE', `/api/v1/assets/${assetId}`);
    check(deleteRes, {
      'delete asset status 204': (r) => r.status === 204,
    }) || errorRate.add(1);
  }
}

// Alternative test: Mixed workload
export function handleMixedWorkload() {
  const scenarios = [
    () => makeRequest('GET', '/api/v1/assets'),
    () => makeRequest('GET', '/api/v1/telemetry'),
    () => makeRequest('GET', '/api/v1/alarms'),
    () => makeRequest('GET', '/api/v1/dashboard'),
    () => makeRequest('GET', '/api/v1/kanban/tasks'),
    () => makeRequest('GET', '/api/v1/registries'),
  ];
  
  const randomScenario = scenarios[Math.floor(Math.random() * scenarios.length)];
  let res = randomScenario();
  
  check(res, {
    'request successful': (r) => r.status === 200,
  }) || errorRate.add(1);
  
  sleep(Math.random() * 2 + 1); // Random sleep between 1-3 seconds
}
