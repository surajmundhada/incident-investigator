# Payment unavailable and HTTP 503 investigation

## Payment HTTP 503

Payment service unavailable records that processing could not complete. Correlate payment HTTP 503 with checkout's payment dependency error using the request ID. Report payment unavailability as an observed symptom. A generic unavailable response does not establish a database, deployment, or upstream-provider diagnosis.

## Competing explanations

The payment process may be reachable while business processing is unavailable. Successful process health does not refute payment request errors. Consider application rejection, temporary capacity limits, configuration problems, and connectivity only when supported by the applicable architecture and additional observations. This simulation has no external payment gateway or application database.

## Check impact and recovery

Compare failed and successful payment requests across the incident window. Matching checkout failures establish user-visible impact. If requests later return 200, report recovery at that time. If signals cannot distinguish causes, provide an inconclusive cause and suggested checks instead of unsupported certainty.

