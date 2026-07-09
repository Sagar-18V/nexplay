const { Queue } = require('bullmq');
const { bullmqConnection } = require('../../config/redis');
module.exports = { webhookQueue: new Queue('webhooks', { connection: bullmqConnection }) };