const autocannon = require('autocannon');
const { token, ids } = require('../../../../loadtest-ids.json');

let i = 0;

autocannon({
    url: 'http://localhost:3000',
    connections: 10,
    duration: 20,
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
});