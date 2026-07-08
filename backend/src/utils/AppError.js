/**
 * Operational error — expected errors that have a meaningful HTTP status.
 * Distinguished from programmer errors (which bubble up as 500s).
 */
class AppError extends Error {
    constructor(message, status = 500) {
        super(message);
        this.name = 'AppError';
        this.status = status;
        Error.captureStackTrace(this, this.constructor);
    }
}

module.exports = AppError;
