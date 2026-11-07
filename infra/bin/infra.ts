#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { LaunchpadStack } from '../lib/launchpad-stack';

const app = new cdk.App();

// Account and region come from the AWS CLI profile (CDK_DEFAULT_ACCOUNT / CDK_DEFAULT_REGION).
new LaunchpadStack(app, 'LaunchpadStack', {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION,
  },
  description: 'LaunchPad foundation: Cognito email login, private uploads bucket, and diagnostic tables.',
});
