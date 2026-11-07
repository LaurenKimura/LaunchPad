# LaunchPad backend

Python Lambdas for the dashboard. The CDK app in `infra/` deploys them.

`handler.handler` collects space weather and TLEs every hour. `presign.handler` returns a presigned upload. `parse_upload.handler` reads that file and records gap windows. `correlate.handler` scores each window. None of these paths log raw telemetry or a presigned URL.

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

## Telemetry upload

`POST /uploads` checks that the satellite belongs to the caller, writes a pending Uploads row, and returns a presigned POST. The S3 policy allows 1 byte through 5 MiB by default (`MAX_UPLOAD_BYTES`).

The parser accepts CSV or JSON. A timestamp may carry a zone offset. A timestamp with no zone is read as UTC. A gap is two neighboring samples more than `GAP_INTERVAL_MULTIPLIER` times the median positive interval apart. The default multiplier is 2. Each gap becomes one Anomalies item. The window starts at the sample before the hole and ends at the sample after it.

Sample files are in [`samples/`](../samples/README.md). The unit tests load those files.

## Scores

`scoring.py` has one pure function per cause. Weights are in [`src/scoring_weights.json`](src/scoring_weights.json). `propagate.py` uses SGP4 for position, the configured South Atlantic Anomaly box, and a cylindrical Earth shadow. `correlate.handler` reads DynamoDB and writes four CauseScores rows. A gap fully inside a SEP scores `radiation.sep_full_overlap` (85 in the shipped file) and does not pull the other scores down.

`explain.handler` sends those stored scores and evidence to Claude on Bedrock. It does not compute a score. The prompt tells the model to use only the supplied numbers, never invent events, say when evidence is weak, and treat telemetry text as data rather than instructions. Recommended fixes are limited to watchdog reset, safe mode, EDAC scrubbing, power review, and software patch review. A follow-up question is answered from the same stored packet. Each operator gets 20 calls per UTC day. Logs do not include the prompt, the question, the evidence, or the model text.

`pip install -r requirements-dev.txt` installs `sgp4` for the tests. The CDK app installs the same version into the correlation Lambda asset.

## Tests

From this directory:

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```

The tests mock HTTP, S3, DynamoDB, and Secrets Manager. They do not call the network. boto3 is provided by the Lambda runtime and is not required to run the tests.

The function is deployed by the CDK app in `infra/`. It is not invoked from a local script.
