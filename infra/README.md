# LaunchPad infrastructure

AWS CDK app (TypeScript) for the foundation of the satellite anomaly dashboard.

This stack creates:

- A Cognito user pool where the username is the operator's email
- A public web app client (no client secret) that signs in with SRP
- A private S3 bucket for telemetry uploads, encrypted with an S3-managed key
- A second private bucket for raw responses from NASA DONKI, NOAA SWPC, and CelesTrak
- Six on-demand DynamoDB tables for satellites, uploads, anomalies, cause scores, space-weather samples, and cached TLEs
- A Secrets Manager secret for the NASA API key
- An hourly Lambda, started by EventBridge, that archives those responses and writes normalized rows
- `POST /uploads` on API Gateway. A signed-in operator receives a presigned POST for one CSV or JSON file
- A parser Lambda, started by the S3 object-created event, that records gap windows on the Anomalies table
- A correlation Lambda that scores each window. The four scores are independent 0–100 values

Bedrock is not in this stack. The fetch Lambda cannot read the telemetry bucket. The correlation Lambda cannot read the uploads bucket.

Account and region come from your AWS CLI configuration. No account id, region, or secret is stored in the repo.

## Deploy

Install the AWS CLI and configure a principal that can create these resources. Then, from this directory:

```bash
npm ci
npx cdk bootstrap
npx cdk synth
npx cdk deploy
```

`cdk bootstrap` is once per account and region. It creates the toolkit bucket CDK deploys from.

`cdk deploy` prints the user pool id, web client id, bucket names, table names, and the NASA secret ARN. The web app will need the pool id and client id later.

CloudFormation keeps the user pool, both buckets, the tables, and the NASA secret when the stack is deleted (`RemovalPolicy.RETAIN`). `cdk destroy` removes the stack but leaves that data. Delete those resources in the console only when you mean to discard them.

### NASA API key

The secret is created with a generated placeholder. DONKI calls fail until you replace it. NOAA and CelesTrak do not use this secret. The hourly job keeps running the other sources when DONKI is down.

```bash
aws secretsmanager put-secret-value \
  --secret-id <NasaDonkiSecretArn> \
  --secret-string '<your NASA API key>'
```

A JSON value `{"api_key":"<your NASA API key>"}` is also accepted. Do not commit the key.

### Tracked satellites for TLE fetch

CelesTrak is queried only for satellites that already have a `noradId` attribute. The hourly job scans the Satellites table for that attribute. An empty table skips the TLE fetch.

```bash
aws dynamodb put-item \
  --table-name <SatellitesTableName> \
  --item '{"satelliteId":{"S":"iss"},"noradId":{"S":"25544"},"ownerSub":{"S":"<cognito sub>"},"name":{"S":"ISS"}}'
```

### First operator

Operators can sign themselves up from the web app. Cognito emails a confirmation code. An admin can still create a user. Replace the pool id with the `UserPoolId` output:

```bash
aws cognito-idp admin-create-user \
  --user-pool-id <UserPoolId> \
  --username operator@example.com \
  --user-attributes Name=email,Value=operator@example.com Name=email_verified,Value=true \
  --desired-delivery-mediums EMAIL
```

Cognito emails a temporary password. The pool uses the Cognito default email sender, which is capped at a small number of messages per day. The operator signs in with that email address. Passwords must be at least 12 characters and include upper case, lower case, a digit, and a symbol.

The pool is on the Lite feature plan. Turn on a higher plan only when you need the extra Cognito features.

## Table access patterns

Every table is on-demand (`PAY_PER_REQUEST`), encrypted with the key DynamoDB owns, and has point-in-time recovery. Global secondary indexes project all attributes, so a query returns the whole item.

Time-ordered sort keys use ISO-8601 UTC strings. `{timestamp}#{id}` still sorts by time, and the id keeps two events in the same instant distinct.

`ownerSub` is the Cognito `sub` claim, not the email, so a changed email does not move rows.

### Satellites

| | |
|---|---|
| Partition key | `satelliteId` |
| Sort key | none |

- **Get one satellite.** `GetItem` on `satelliteId`.
- **List the signed-in operator's satellites.** Query index `byOwner`: partition key `ownerSub`, sort key `satelliteId`.

### Uploads

| | |
|---|---|
| Partition key | `satelliteId` |
| Sort key | `uploadedAtUploadId` = `{uploadedAt}#{uploadId}` |

- **List uploads for a satellite, newest first.** Query `satelliteId`, reverse sort order.
- **Load one upload by id.** Query index `byUploadId`: partition key `uploadId`. Used by the results page and by processing.
- **List the operator's uploads across satellites.** Query index `byOwner`: partition key `ownerSub`, sort key `uploadedAtUploadId`.

### Anomalies

| | |
|---|---|
| Partition key | `uploadId` |
| Sort key | `startTimeAnomalyId` = `{start time}#{anomalyId}` |

- **Timeline for one file.** Query `uploadId`. Rows come back in start-time order.
- **Open one anomaly.** Query index `byAnomalyId`: partition key `anomalyId`.
- **Recent gaps for one satellite.** Query index `bySatellite`: partition key `satelliteId`, sort key `startTimeAnomalyId`. The software score uses this to look for a repeating pattern.

### CauseScores

| | |
|---|---|
| Partition key | `anomalyId` |
| Sort key | `causeId` |

One row per cause (`radiation`, `eclipse_power`, `geomagnetic`, `software_system`). Each row holds its own 0–100 likelihood. Nothing in the table combines those numbers into a share of 100.

- **Scores for one gap.** Query `anomalyId`. The sort key is the cause name, so a gap has one row per cause.
- **Every score on an upload.** Query index `byUpload`: partition key `uploadId`, sort key `anomalyIdCauseId` = `{anomalyId}#{causeId}`.

### SpaceWeatherEvents

| | |
|---|---|
| Partition key | `dataset` |
| Sort key | `observedAt` |

These rows are public space-weather samples, not satellite telemetry. The hourly job writes:

- `noaa_kp` for the planetary K index
- `noaa_proton_10mev` and the other GOES integral channels (`1`, `5`, `30`, `50`, `60`, `100`, `500` MeV)
- `donki_sep`, `donki_flr`, `donki_cme`, `donki_gst`

NOAA sort keys are plain ISO-8601 UTC timestamps. DONKI sort keys are `{timestamp}#{eventId}`, so two events that start in the same second are both kept. These rows store observations, not cause scores.

- **Samples that overlap a gap.** Query `dataset` with `observedAt` between the gap start and `{end}~`. The `~` sorts after `#`, so a DONKI id at the end timestamp is included.
- **Sample in effect at a moment.** Query `dataset` with `observedAt` less than or equal to `{time}~`, reverse order, limit 1. Use this on the NOAA datasets, whose keys are plain timestamps.

### TLECache

| | |
|---|---|
| Partition key | `satelliteId` |
| Sort key | `epoch` (TLE epoch, ISO-8601 UTC) |

- **Newest cached elements.** Query `satelliteId`, reverse order, limit 1.
- **Elements to use for a gap.** Query `satelliteId` with `epoch` less than or equal to the gap time, reverse order, limit 1.

A later fetch of the same satellite and epoch overwrites that one cache row.

## Hourly fetch

EventBridge invokes the Lambda every hour. The function reads the NASA key from Secrets Manager, then fetches:

- NASA DONKI SEP, FLR, CME, and GST for the last 7 days
- NOAA SWPC planetary K index and GOES integral proton flux
- A CelesTrak TLE for each satellite that has `noradId`

Raw bodies go to `s3://<ExternalRawBucket>/raw/...`. The last good body for each source also sits under `cache/...`. Normalized rows go to SpaceWeatherEvents and TLECache. A 304 response, or a body whose hash matches the cache, does not write DynamoDB again.

If one upstream is down, the others still run. The failed source leaves the previous cache and table rows in place and tries again on the next hour. The function logs the source name and a short error code. It does not log the NASA key, request URLs, raw bodies, or telemetry.

The Lambda role is limited to `s3:GetObject` and `s3:PutObject` on `raw/*` and `cache/*` in the external bucket, `dynamodb:PutItem` and `dynamodb:BatchWriteItem` on the space-weather and TLE tables, `dynamodb:Scan` on Satellites, and `secretsmanager:GetSecretValue` on the NASA secret.

Python tests for the fetch live in `backend/` (`pytest`). See `backend/README.md`.

## Operator API

Every route requires a Cognito ID token in the `Authorization` header. A missing token is rejected by API Gateway. A row owned by someone else is returned as `404`, the same as a missing row.

| Method | Path | What it returns |
|---|---|---|
| `GET` | `/satellites` | Satellites whose `ownerSub` is the caller |
| `GET` | `/anomalies` | Newest gaps across those satellites. Optional `satelliteId` and `limit` (max 50) |
| `GET` | `/anomalies/{anomalyId}` | One gap, its cause scores, a timeline of overlapping space-weather and eclipse intervals, the latest Kp, and recent events |
| `POST` | `/uploads` | A presigned POST for one CSV or JSON file |

The read role can query Satellites (`byOwner` and get-by-id), Anomalies (`bySatellite`, `byAnomalyId`), CauseScores, SpaceWeatherEvents, and TLECache. It cannot write those tables or read S3. The timeline uses the same DONKI association windows as scoring. Eclipse bars come from SGP4 over the gap. The latest Kp is the newest `noaa_kp` row at or before the request. The same response includes the TLE in effect at the gap start and the South Atlantic Anomaly box from the scoring weights, so the globe can draw the orbit. The TLE lines are not written to the logs.

## Telemetry upload

`POST {UploadApiUrl}uploads` with a Cognito ID token in `Authorization`. The token is the ID token from the operator pool. The body is JSON:

```json
{"satelliteId": "iss", "contentType": "text/csv"}
```

`contentType` is `text/csv` or `application/json`. The satellite must belong to the caller. A missing satellite and a satellite owned by someone else both return `404`, so callers cannot probe ids.

The response is a presigned POST, not a PUT. S3 rejects an object outside 1 byte to 5 MiB (`MAX_UPLOAD_BYTES`). The signed policy also pins the object key, the content type, and SSE-S3. The URL expires in 15 minutes. Send the returned `fields` as form fields and the file last, under the field name `file`. The uploads bucket allows browser POST from any origin so the later web app can upload. Tighten that origin when the site hostname is known.

The object key is `uploads/{satelliteId}/{uploadId}/{uploadedAt}/telemetry.csv` (or `.json`). The client's filename is not used.

When the object is created, EventBridge invokes the parser. The parser:

- ignores keys that do not match that pattern, and does not download them
- rejects a file larger than 5 MiB or more than 100,000 timestamp rows
- accepts CSV with a `timestamp`, `time`, or `ts` column, or JSON as a list or as `{ "samples" | "records" | "data": [...] }`
- converts each timestamp to UTC (an offset is honored; a timestamp with no zone is read as UTC)
- flags a gap when two neighboring samples are more than `GAP_INTERVAL_MULTIPLIER` times the median positive interval apart (default 2)
- writes one Anomalies row per gap window and sets the upload status to `parsed` or `rejected`
- asks the correlation Lambda to score the upload when at least one gap was saved. The message contains the upload id and satellite id

A bad file is a finished result, not a retry. An S3 or DynamoDB error is retried twice. If the correlation invoke fails, the upload stays `pending` so the event can be tried again. Logs contain the upload id, the sample count, the gap count, and an error code. They do not contain the file body or the presigned URL.

The presign role can `s3:PutObject` on `uploads/*`, `dynamodb:GetItem` on Satellites, and `dynamodb:PutItem` on Uploads. The parser role can `s3:GetObject` on `uploads/*`, get and update Uploads, and put Anomalies rows. Neither role can delete an object.

Sample files and the expected gap windows are in [`samples/README.md`](../samples/README.md).

## Correlation

After a file parses, the correlation Lambda loads that upload's anomaly windows, the cached TLE with `epoch` at or before the gap, and space-weather rows from the lookback in `scoring_weights.json`. It propagates the TLE with SGP4, then writes four CauseScores rows:

| causeId | What raises the score |
|---|---|
| `radiation` | SEP, >=10 MeV proton flux, flare class, CME overlap, and time inside the South Atlantic Anomaly box |
| `eclipse_power` | Fraction of propagated samples in Earth shadow |
| `geomagnetic` | Kp, and a GST that overlaps the gap |
| `software_system` | Other gaps on the same satellite with a similar duration or a regular spacing. No space weather and no orbit |

Each score is clamped to 0–100 on its own. They are not rescaled to sum to 100. Weights live in [`backend/src/scoring_weights.json`](../backend/src/scoring_weights.json). Every row includes the evidence lines and the disclaimer that these are estimates, not confirmed root causes.

A gap that sits fully inside a SEP association window scores high on radiation (the `sep_full_overlap` weight, 85 with the shipped config) even when the other three scores are zero.

The correlation role can query Anomalies (including `bySatellite`), SpaceWeatherEvents, and TLECache, and can write CauseScores. It cannot read S3 or the NASA secret. Logs contain ids and the four numbers, not evidence text and not telemetry.

`cdk synth` installs `sgp4==2.23` with the local `python3`. That interpreter needs to be 3.12 so the wheel matches the Lambda runtime.

## What this stack does not do

It does not call Bedrock. Do not log raw telemetry.
