import accountHandlers from './handlers/account.handler'
import healthHandlers from './handlers/health.handler'

// Keep the mock surface explicit and aligned with the frozen A1 contracts.
export default [...accountHandlers, ...healthHandlers]
