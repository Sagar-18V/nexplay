const BASE = 'http://localhost:3000/v1';
const EMAIL = 'sagar1116srv@gmail.com';
const PASSWORD = 'Sagar@1627';
const COUNT = 50;
const autocannon = require('autocannon');
const { token, ids } = require('../../../../loadtest-ids.json');
let i = 0;

autocannon({
    url: 'http://localhost:3000',
    connections: 10,
    amount: 50,          // exactly 50 requests total — no duration, no repeat-hitting
    requests: [
        {
            setupRequest: (req) => {
                const id = ids[i % ids.length];
                i++;
                return {
                    ...req,
                    method: 'POST',
                    path: `/v1/payments/intents/${id}/process`,
                    headers: { authorization: `Bearer ${token}` },
                };
            },
        },
    ],
}, (err, result) => {
    if (err) return console.error(err);
    console.log(autocannon.printResult(result));
    console.log(`\n${result['2xx']} 2xx, ${result.non2xx} non-2xx`);
});

async function login() {
    const res = await fetch(`${BASE}/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
    });
    return (await res.json()).data.accessToken;
}

async function seed() {
    const token = await login();
    const headers = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };
    const ids = [];

    for (let i = 0; i < COUNT; i++) {
        const res = await fetch(`${BASE}/payments/intents`, {
            method: 'POST',
            headers: { ...headers, 'Idempotency-Key': `loadtest-${Date.now()}-${i}` },
            body: JSON.stringify({ amount: 10000 + i, method: ['CARD', 'UPI', 'NET_BANKING'][i % 3] }),
        });
        const json = await res.json();
        if (!json.data?.id) {
            console.log('Status:', res.status, 'Body:', JSON.stringify(json));
            process.exit(1);
        }
        ids.push(json.data.id);
        if (i % 50 === 0) console.log(`seeded ${i}/${COUNT}`);
    }

    require('fs').writeFileSync('loadtest-ids.json', JSON.stringify({ token, ids }));
    console.log(`Done. ${ids.length} intents ready in loadtest-ids.json`);
}

seed().catch(console.error);