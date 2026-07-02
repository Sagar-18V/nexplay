const { Queue, FlowProducer } = require('bullmq');
const connection = require('../../../config/redis'); // your existing ioredis instance

const RECON_GATEWAY_QUEUE = 'recon-gateway';
const RECON_RUN_QUEUE = 'recon-run';

const reconGatewayQueue = new Queue(RECON_GATEWAY_QUEUE, { connection });
const reconRunQueue = new Queue(RECON_RUN_QUEUE, { connection });
const flowProducer = new FlowProducer({ connection });

module.exports = {
    RECON_GATEWAY_QUEUE,
    RECON_RUN_QUEUE,
    reconGatewayQueue,
    reconRunQueue,
    flowProducer,
};
