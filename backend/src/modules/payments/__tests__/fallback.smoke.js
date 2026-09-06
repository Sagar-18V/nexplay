/**
 * Fallback simulation: fires N payments through the live API,
 * tallies first-attempt success vs fallback-rescued vs fully exhausted.
 * Run: node src/modules/payments/__tests__/fallback.smoke.js
 */
const BASE = 'http://localhost:3000/v1';
const EMAIL = 'sagar1116srv@gmail.com';
const PASSWORD = 'Sagar@1627';
const N = 30;

async function login() {
    const res = await fetch(`${BASE}/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
    });
    console.log(res, "login data2ß")

    return (await res.json()).data.accessToken;
}

async function run() {
    const token = await login();
    const headers = { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` };

    let firstAttempt = 0, rescued = 0, exhausted = 0, failed = 0;

    for (let i = 0; i < N; i++) {
        // WALLET biases SwiftPay first — SwiftPay is the flakiest, best for triggering fallback
        const createRes = await fetch(`${BASE}/payments/intents`, {
            method: 'POST', headers: { ...headers, 'Idempotency-Key': `fallback-sim-${Date.now()}-${i}` },
            body: JSON.stringify({ amount: 150000, method: 'WALLET' }),
        });
        const intent = (await createRes.json()).data;

        const procRes = await fetch(`${BASE}/payments/intents/${intent.id}/process`, {
            method: 'POST', headers,
        });
        const body = (await procRes.json()).data;

        const succeeded = body.transactions.some((t) => t.status === 'SUCCESS');
        const attempts = body.tried.length;

        if (succeeded && attempts === 1) firstAttempt++;
        else if (succeeded && attempts > 1) rescued++;
        else if (!succeeded) exhausted++;
        else failed++;

        process.stdout.write(`${i + 1}/${N}: ${body.tried.join('→')} ${succeeded ? '✓' : '✗'}\n`);
    }

    console.log('\n--- Results ---');
    console.log(`First-attempt success: ${firstAttempt}`);
    console.log(`Rescued by fallback:   ${rescued}`);
    console.log(`Fully exhausted:       ${exhausted}`);
    console.log(`Fallback save rate:    ${((rescued / (rescued + exhausted || 1)) * 100).toFixed(1)}% of initial failures recovered`);
}

run().catch(console.error);