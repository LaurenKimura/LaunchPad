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

Scoring code, API Gateway, and Bedrock are not in this stack yet. The fetch Lambda cannot read the telemetry bucket.

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

Self sign-up is off. Create an operator with the email address they will type on the sign-in form. Replace the pool id with the `UserPoolId` output:

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

### CauseScores

| | |
|---|---|
| Partition key | `anomalyId` |
| Sort key | `causeId` |

One row per cause. Each row holds its own 0–100 likelihood. Nothing in the table combines those numbers into a share of 100.

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

## What this stack does not do

It does not accept telemetry uploads, score anomalies, or call Bedrock. Those policies arrive with the Lambdas that need them. Do not log raw telemetry.
