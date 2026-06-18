const express = require('express');
const router = express.Router();
const { register, login, refresh, me } = require('./auth.controller');
const authenticate = require('../../middleware/authenticate');

router.post('/register', register);
router.post('/login', login);
router.post('/refresh', refresh);
router.get('/me', authenticate, me);

module.exports = router;