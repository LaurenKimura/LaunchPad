# LaunchPad

Satellite anomaly diagnostic dashboard. An operator uploads a telemetry file with gaps or errors. The app correlates each gap with space weather, orbital position (South Atlantic Anomaly and Earth-shadow eclipse), and software-fault patterns, then shows an independent likelihood and a plain-English fix for each cause.

Scores are estimates from 0 to 100. Each cause stands on its own: the numbers are not forced to sum to 100. Python computes every score. Bedrock, when it is added, only explains numbers it is given.

An hourly Lambda in [`backend/`](backend/README.md) fetches NASA DONKI, NOAA SWPC, and CelesTrak. It stores raw responses in a private S3 bucket and normalized rows in DynamoDB. The NASA key lives in Secrets Manager.

A signed-in operator calls `POST /uploads` and receives a presigned POST. The file is limited to 5 MiB. After it lands, a parser converts timestamps to UTC and records each gap longer than twice the median sampling interval. A correlation Lambda then writes four independent 0–100 scores for radiation, eclipse, geomagnetic activity, and repeating software patterns. Example files are in [`samples/`](samples/README.md). The score weights are in [`backend/src/scoring_weights.json`](backend/src/scoring_weights.json).

## Deploy

Infrastructure is an AWS CDK app in [`infra/`](infra/README.md). From a machine with the AWS CLI configured for the account and region you want:

```bash
cd infra
npm ci
npx cdk bootstrap
npx cdk deploy
```

Bootstrap once per account and region. Deploy prints the Cognito user pool id, the web client id, the bucket names, the DynamoDB table names, and the NASA secret ARN. Replace that secret with a real NASA API key before DONKI fetches succeed. The command is in [`infra/README.md`](infra/README.md).

The user pool signs operators in with email. Self sign-up is off; create the first user with the command in [`infra/README.md`](infra/README.md). That file also records the partition key, sort key, and access pattern for each table.

`cdk destroy` deletes the stack and leaves the user pool, the buckets, the tables, and the NASA secret in place.
