# LaunchPad fetch Lambda

Hourly Python function. EventBridge in the CDK stack starts it. It collects public space-weather and orbit data used later when an upload is diagnosed.

## Sources

| Source | What is fetched | Normalized table |
|---|---|---|
| NASA DONKI | SEP, FLR, CME, GST for the last 7 days | `SpaceWeatherEvents` |
| NOAA SWPC | Planetary K index | `SpaceWeatherEvents` (`dataset = noaa_kp`) |
| NOAA SWPC | GOES primary integral proton flux, 1 day | `SpaceWeatherEvents` (`dataset = noaa_proton_<channel>`) |
| CelesTrak | TLE (`FORMAT=TLE`) for each satellite with a `noradId` | `TLECache` |

The NASA key is read from Secrets Manager (`NASA_SECRET_ARN`). NOAA and CelesTrak are public and do not use that secret. Set the key after deploy; the command is in [`infra/README.md`](../infra/README.md).

## Cache and outages

Each source keeps two S3 objects in the external raw bucket:

- `raw/<source>/<date>/<timestamp>` archives a new body. The bucket expires `raw/` after 30 days.
- `cache/...` is the last body that was normalized and written to DynamoDB.

A `304` response, or a new body with the same SHA-256 as the cache, skips the table write. HTTP 429 and 5xx responses are retried three times with exponential backoff (0.5s, 1s, 2s, plus jitter). Other HTTP errors are not retried.

One source can fail without stopping the others. A failure does not delete the previous cache or the previous table rows. The next hour tries again. The run result lists each source as `ok`, `cached`, `skipped`, `partial`, or `outage`.

Logs contain the source name, status, item count, and a short error code. They do not contain the NASA key, the request URL, the raw body, or telemetry.

## Sort keys

NOAA rows use a plain ISO-8601 UTC `observedAt`. DONKI rows use `{timestamp}#{eventId}` so two events at the same second are both stored. Query details are in [`infra/README.md`](../infra/README.md).

TLE rows use `satelliteId` and the element-set epoch. The epoch is taken from columns 19-32 of TLE line 1.

## Tests

From this directory:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```

The tests mock HTTP, S3, DynamoDB, and Secrets Manager. They do not call the network. boto3 is provided by the Lambda runtime and is not required to run the tests.

The function is deployed by the CDK app in `infra/`. It is not invoked from a local script.
