const { Queue, FlowProducer } = require('bullmq');
const { bullmqConnection } = require('../../../config/redis'); // your existing ioredis instance

const RECON_GATEWAY_QUEUE = 'recon-gateway';
const RECON_RUN_QUEUE = 'recon-run';

const reconGatewayQueue = new Queue(RECON_GATEWAY_QUEUE, { connection: bullmqConnection });
const reconRunQueue = new Queue(RECON_RUN_QUEUE, { connection: bullmqConnection });
const flowProducer = new FlowProducer({ connection: bullmqConnection });

module.exports = {
    RECON_GATEWAY_QUEUE,
    RECON_RUN_QUEUE,
    reconGatewayQueue,
    reconRunQueue,
    flowProducer,
};
