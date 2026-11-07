# LaunchPad infrastructure

AWS CDK app (TypeScript) for the foundation of the satellite anomaly dashboard.

This stack creates:

- A Cognito user pool where the username is the operator's email
- A public web app client (no client secret) that signs in with SRP
- A private S3 bucket for telemetry uploads, encrypted with an S3-managed key
- Six on-demand DynamoDB tables for satellites, uploads, anomalies, cause scores, space-weather samples, and cached TLEs

Scoring code, Lambdas, API Gateway, and Bedrock are not in this stack yet.

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

`cdk deploy` prints the user pool id, web client id, uploads bucket name, and the six table names. The web app will need the pool id and client id later.

CloudFormation keeps the user pool, the bucket, and the tables when the stack is deleted (`RemovalPolicy.RETAIN`). `cdk destroy` removes the stack but leaves that data. Delete those resources in the console only when you mean to discard them.

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
| Partition key | `dataset` (`kp`, `dst`, `proton_10mev`, and so on) |
| Sort key | `observedAt` (ISO-8601 UTC) |

These rows are public space-weather samples, not satellite telemetry.

- **Samples that overlap a gap.** Query `dataset` with `observedAt` between the gap start and end.
- **Sample in effect at a moment.** Query `dataset` with `observedAt` less than or equal to that moment, reverse order, limit 1.

### TLECache

| | |
|---|---|
| Partition key | `satelliteId` |
| Sort key | `epoch` (TLE epoch, ISO-8601 UTC) |

- **Newest cached elements.** Query `satelliteId`, reverse order, limit 1.
- **Elements to use for a gap.** Query `satelliteId` with `epoch` less than or equal to the gap time, reverse order, limit 1.

A later fetch of the same satellite and epoch overwrites that one cache row.

## What this stack does not do

It does not grant application roles, accept uploads, or read the tables. Those policies arrive with the Lambdas, scoped to the actions each function needs. Do not log raw telemetry when that code is added. The bucket is the place the file bytes go; the tables store ids, timestamps, scores, and short evidence summaries.
