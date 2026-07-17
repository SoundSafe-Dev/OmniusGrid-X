import { describe, it, expect } from 'vitest';
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios';
import { registerTransform, requestTransform, responseTransform } from './transformRegistry';

registerTransform('/api/v1/__regtest', {
  inAliases: { wireName: 'name' },
  outAliases: { name: 'wire_name' },
});

const req = (url: string, data?: unknown, params?: unknown) =>
  ({ url, data, params, headers: {} }) as InternalAxiosRequestConfig;

const res = (url: string, data: unknown, responseType?: string) =>
  ({ config: { url, responseType }, data }) as unknown as AxiosResponse;

describe('transformRegistry', () => {
  it('transforms request bodies + params only under registered prefixes', () => {
    const hit = requestTransform(req('/api/v1/__regtest/things', { someField: 1 }, { pageSize: 2 }));
    expect(hit.data).toEqual({ some_field: 1 });
    expect(hit.params).toEqual({ page_size: 2 });

    const miss = requestTransform(req('/api/v1/nlp/sessions', { someField: 1 }));
    expect(miss.data).toEqual({ someField: 1 }); // never-list prefix untouched
  });

  it('does not partial-match sibling prefixes', () => {
    const sibling = requestTransform(req('/api/v1/__regtest_other/x', { someField: 1 }));
    expect(sibling.data).toEqual({ someField: 1 });
  });

  it('skips FormData/URLSearchParams bodies', () => {
    const fd = new FormData();
    const out = requestTransform(req('/api/v1/__regtest/upload', fd));
    expect(out.data).toBe(fd);
    const usp = new URLSearchParams('a=1');
    expect(requestTransform(req('/api/v1/__regtest/x', usp)).data).toBe(usp);
  });

  it('camelizes responses with aliases; skips blobs and unregistered urls', () => {
    const r = responseTransform(res('/api/v1/__regtest/things', [{ wire_name: 'a', created_at: 't' }]));
    // snake->camel first, then alias wireName->name
    expect(r.data).toEqual([{ name: 'a', createdAt: 't' }]);

    const blob = res('/api/v1/__regtest/file', new Blob(['x']), 'blob');
    expect(responseTransform(blob).data).toBeInstanceOf(Blob);

    const miss = responseTransform(res('/api/v1/user/goals', { goal_type: 'x' }));
    expect(miss.data).toEqual({ goal_type: 'x' });
  });

  it('is idempotent on already-camel payloads (mixed-casing backends, 401 retries)', () => {
    const once = responseTransform(res('/api/v1/__regtest/things', { vehicleNumber: 'V1' }));
    const twice = responseTransform(res('/api/v1/__regtest/things', once.data));
    expect(twice.data).toEqual({ vehicleNumber: 'V1' });
  });
});
