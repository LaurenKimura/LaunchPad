# LaunchPad

Satellite anomaly diagnostic dashboard. An operator uploads a telemetry file with gaps or errors. The app correlates each gap with space weather, orbital position (South Atlantic Anomaly and Earth-shadow eclipse), and software-fault patterns, then shows an independent likelihood and a plain-English fix for each cause.

Scores are estimates from 0 to 100. Each cause stands on its own: the numbers are not forced to sum to 100. Python computes every score. Bedrock, when it is added, only explains numbers it is given.

## Deploy

Infrastructure is an AWS CDK app in [`infra/`](infra/README.md). From a machine with the AWS CLI configured for the account and region you want:

```bash
cd infra
npm ci
npx cdk bootstrap
npx cdk deploy
```

Bootstrap once per account and region. Deploy prints the Cognito user pool id, the web client id, the uploads bucket name, and the DynamoDB table names.

The user pool signs operators in with email. Self sign-up is off; create the first user with the command in [`infra/README.md`](infra/README.md). That file also records the partition key, sort key, and access pattern for each table.

`cdk destroy` deletes the stack and leaves the user pool, the uploads bucket, and the tables in place.
