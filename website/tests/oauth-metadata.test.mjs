import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

test('public native OAuth identity contains no per-user credentials or callbacks', () => {
  const doc = JSON.parse(readFileSync(new URL('../public/oauth/client-metadata.json', import.meta.url)));
  assert.equal(doc.client_id, 'https://umbod.ai/oauth/client-metadata.json');
  assert.equal(doc.token_endpoint_auth_method, 'none');
  assert.equal(doc.application_type, 'native');
  assert.deepEqual(doc.redirect_uris, ['http://127.0.0.1/desktop/oauth/callback']);
  assert.equal(doc.client_secret, undefined);
  assert.deepEqual(doc.response_types, ['code']);
});
