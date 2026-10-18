/**
 * Wrap an async EventEmitter handler so a rejection is logged instead of becoming an
 * unhandled promise rejection. Node >= 15 terminates the process on those, and the
 * BullMQ workers run inside the API process (src/workers.js), so before this a single
 * failed DB write in a worker's 'failed' handler took the whole HTTP API down.
 */
function safeHandler(name, fn) {
    return (...args) => {
        Promise.resolve()
            .then(() => fn(...args))
            .catch((err) => {
                console.error(JSON.stringify({
                    level: 'error',
                    handler: name,
                    message: err.message,
                    stack: err.stack,
                    timestamp: new Date().toISOString(),
                }));
            });
    };
}

module.exports = { safeHandler };
