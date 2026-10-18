// Regenerate recon_node_vector.json from the REAL Node generator + engine (Prisma stubbed).
// From backend/:  node ../api-py/tests/unit/fixtures/make_recon_vector.js ../api-py/tests/unit/fixtures/recon_node_vector.json
// Run the REAL Node generator + engine on fixed input; Prisma replaced by a stub.
const path = require('path');
const prisma = require(path.resolve('src/config/prisma'));
const DAY = new Date('2026-10-17T00:00:00.000Z');
const mk = (gw, n) => Array.from({ length: n }, (_, i) => {
  const createdAt = new Date(DAY.getTime() + i * 61_000 + 7);
  return { id: `${gw.toLowerCase()}-txn-${String(i).padStart(3, '0')}`, gateway: gw,
           amount: 1000 + i * 137, status: i % 5 === 0 ? 'FAILED' : 'SUCCESS',
           createdAt, updatedAt: createdAt };   // updatedAt supplied so Node doesn't hit D19
});
const data = { RAZORX: mk('RAZORX', 220), STRIPEIN: mk('STRIPEIN', 140), PAYFLOW: mk('PAYFLOW', 90), SWIFTPAY: mk('SWIFTPAY', 30) };
prisma.transaction.findMany = async ({ where }) => data[where.gateway];
const { generateSettlementFile } = require(path.resolve('src/modules/settlements/settlementFileGenerator'));
const { reconcile } = require(path.resolve('src/modules/reconciliation/reconciliationEngine'));
(async () => {
  const out = { day: DAY.toISOString(), seeds: {}, gateways: {} };
  // raw PRNG stream for a few seeds
  const src = require('fs').readFileSync(path.resolve('src/modules/settlements/settlementFileGenerator.js'), 'utf8');
  const seededRandom = new Function(src.match(/function seededRandom[\s\S]*?\n}\n/)[0] + '; return seededRandom;')();
  for (const s of ['RAZORX:2026-10-17', 'SWIFTPAY:2026-01-01', 'x']) { const r = seededRandom(s); out.seeds[s] = Array.from({ length: 5 }, r); }
  for (const gw of Object.keys(data)) {
    const file = await generateSettlementFile(gw, DAY);
    const { summary, discrepancies } = reconcile(data[gw].map(({ id, amount, status }) => ({ id, amount, status })), file);
    out.gateways[gw] = { payments: data[gw].map(p => ({ id: p.id, amount: p.amount, status: p.status, createdAt: p.createdAt.toISOString() })),
      file, summary: Object.fromEntries(Object.entries(summary).map(([k, v]) => [k, typeof v === 'bigint' ? Number(v) : v])),
      discrepancies: discrepancies.map(d => Object.fromEntries(Object.entries(d).map(([k, v]) => [k, typeof v === 'bigint' ? Number(v) : v]))) };
  }
  require('fs').writeFileSync(process.argv[2], JSON.stringify(out));
  const s = Object.fromEntries(Object.entries(out.gateways).map(([g, v]) => [g, `${v.summary.matchedCount}/${v.summary.totalInDb} matched, ${v.summary.discrepancyCount} discrepancies`]));
  console.log(s); process.exit(0);
})();
