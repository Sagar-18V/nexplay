const { Queue } = require('bullmq');
const connection = require('../../config/redis');
module.exports = { webhookQueue: new Queue('webhooks', { connection }) };