// Authorization middleware. Must run AFTER `authenticate`, which populates
// req.merchant (including req.merchant.role).

// requireRole('ADMIN') or requireRole('ADMIN', 'MERCHANT')
// Allows the request through only if the authenticated merchant's role is in
// the allowed set.
function requireRole(...allowedRoles) {
    return (req, res, next) => {
        if (!req.merchant) {
            return res.status(401).json({
                success: false,
                message: 'Authentication required'
            });
        }

        if (!allowedRoles.includes(req.merchant.role)) {
            return res.status(403).json({
                success: false,
                message: 'Insufficient permissions'
            });
        }

        next();
    };
}

// Resource-ownership guard. Ensures the authenticated merchant may only act on
// their own resources. `getOwnerId` extracts the owning merchantId from the
// request (defaults to the `:merchantId` route param). ADMINs bypass the check.
//
//   router.get('/merchants/:merchantId/settlements',
//       authenticate, requireOwnership(), handler)
//
//   requireOwnership(req => req.body.merchantId)
function requireOwnership(getOwnerId = (req) => req.params.merchantId) {
    return (req, res, next) => {
        if (!req.merchant) {
            return res.status(401).json({
                success: false,
                message: 'Authentication required'
            });
        }

        // Admins are allowed to access any merchant's resources.
        if (req.merchant.role === 'ADMIN') return next();

        const ownerId = getOwnerId(req);

        if (!ownerId || ownerId !== req.merchant.id) {
            return res.status(403).json({
                success: false,
                message: 'You do not have access to this resource'
            });
        }

        next();
    };
}

module.exports = { requireRole, requireOwnership };
