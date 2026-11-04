# Inventory availability and checkout failures

## Inventory is checked before payment

Checkout queries inventory availability before payment. If inventory fails, checkout records inventory as the dependency and does not proceed to payment. A missing payment call may be expected control flow. Do not diagnose payment solely because checkout did not finish.

## Compare inventory observations

Use the same request ID and window to compare inventory and checkout. Inventory 200 with a later payment failure argues against inventory causing that request's checkout error. Unavailable inventory telemetry cannot establish inventory health, even if another source returns no errors.

