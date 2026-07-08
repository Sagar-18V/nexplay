const adapters = {
    RAZORX: require('./razorx.adapter'),
    STRIPEIN: require('./stripein.adapter'),
    PAYFLOW: require('./payflow.adapter'),
    SWIFTPAY: require('./swiftpay.adapter'),
};

function getGatewayAdapter(gateway) {
    const adapter = adapters[gateway];
    if (!adapter) throw new Error(`Unknown gateway: ${gateway}`);
    return adapter;
}

module.exports = { getGatewayAdapter };