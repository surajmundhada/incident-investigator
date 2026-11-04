param([string]$BaseUrl = 'http://127.0.0.1:8000')
$ErrorActionPreference = 'Stop'
$BaseUrl = $BaseUrl.TrimEnd('/')
$windowEnd = [DateTimeOffset]::UtcNow
$payload = @{
    title = 'Payment failures'
    service = 'payment'
    description = 'Checkout requests cannot complete payment authorization'
    starts_at = $windowEnd.AddMinutes(-10).ToString('o')
    ends_at = $windowEnd.ToString('o')
} | ConvertTo-Json
$headers = @{ 'Idempotency-Key' = [Guid]::NewGuid().ToString() }
$result = Invoke-RestMethod -Uri ($BaseUrl + '/api/incidents') -Method Post -ContentType 'application/json' -Headers $headers -Body $payload
$result | ConvertTo-Json
Write-Output ('Inspect: ' + $BaseUrl + '/api/investigations/' + $result.investigation_id)
