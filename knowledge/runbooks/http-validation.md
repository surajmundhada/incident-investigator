# Cart validation and HTTP client errors

## Invalid carts

The checkout schema accepts the book item and quantities from one through ten. A missing or invalid field, zero quantity, or quantity eleven is rejected with HTTP 422 before business processing. Extra fields are forbidden. Invalid input is not evidence of a failing dependency.

## Client errors versus dependency failures

HTTP 422 describes invalid cart input. HTTP 502 describes checkout failing to complete a downstream call. Compare the response, dependency field, and correlated logs. Do not attribute a rejected cart to payment or inventory without observations of those services.
