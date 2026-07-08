const { Queue } = require('bullmq');
const { bullmqConnection } = require('../../config/redis');

const refundQueue = new Queue('refunds', { connection: bullmqConnection });

module.exports = { refundQueue };