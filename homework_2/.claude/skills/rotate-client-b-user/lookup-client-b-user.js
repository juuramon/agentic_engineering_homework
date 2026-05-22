/**
 * Lookup Client B user in YourApp Portal API
 * Usage: node .claude/skills/rotate-client-b-user/lookup-client-b-user.js <userNumber>
 * Example: node .claude/skills/rotate-client-b-user/lookup-client-b-user.js 28
 */

const https = require('node:https');

const userNumber = process.argv[2];
if (!userNumber) {
  console.error('Usage: node lookup-client-b-user.js <userNumber>');
  console.error('Example: node lookup-client-b-user.js 28');
  process.exit(1);
}

function request(options, body) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (d) => (data += d));
      res.on('end', () => resolve({ status: res.statusCode, body: data }));
    });
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

async function main() {
  // Authenticate
  const loginResp = await request(
    {
      hostname: 'accounts.uat.your-app.example.com',
      path: '/impadminclient/login',
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    },
    JSON.stringify({
      username: process.env.PORTAL_USERNAME || '<PORTAL_USERNAME>',
      password: process.env.PORTAL_PASSWORD || '<PORTAL_PASSWORD>',
    }),
  );

  if (loginResp.status !== 200) {
    console.error('Login failed with status:', loginResp.status);
    process.exit(1);
  }

  const token = JSON.parse(loginResp.body).access_token;

  // Search for user
  const email = `test_inm_${userNumber}@mailinator.com`;
  const searchResp = await request({
    hostname: 'api.uat.your-app.example.com',
    path: `/v1/customers/search/${encodeURIComponent(email)}`,
    method: 'GET',
    headers: {
      authorization: `Bearer ${token}`,
      'client-id': 'client-b',
      accept: 'application/json, text/plain, */*',
      'cache-control': 'no-cache',
    },
  });

  if (searchResp.status !== 200) {
    console.error(`Search failed with status: ${searchResp.status}`);
    console.error(
      'If 403, check that client-id header is correct (not x-client-id)',
    );
    process.exit(1);
  }

  const data = JSON.parse(searchResp.body);
  if (!data.customers || data.customers.length === 0) {
    console.error(`No customer found for ${email}`);
    console.error(
      'The user may not have interacted with YourApp yet. Run a subscription test first.',
    );
    process.exit(1);
  }

  const customer = data.customers[0];
  const today = new Date().toISOString().split('T')[0];
  console.log('=== Client B User Found ===');
  console.log(`Customer ID: ${customer.id}`);
  console.log(`Name:        ${customer.name}`);
  console.log(`Email:       ${customer.email}`);
  console.log('');
  console.log('Copy this into consts.ts:');
  console.log(`  email: '${customer.email}',`);
  console.log(`  name: '${customer.name}',`);
  console.log(`  id: '${customer.id}',`);
  console.log(`  rotated: '${today}'`);
}

main().catch((err) => {
  console.error('Error:', err.message);
  process.exit(1);
});
