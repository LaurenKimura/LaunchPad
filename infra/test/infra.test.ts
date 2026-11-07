import * as cdk from 'aws-cdk-lib/core';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { LaunchpadStack } from '../lib/launchpad-stack';

function template(): Template {
  const app = new cdk.App();
  const stack = new LaunchpadStack(app, 'Test');
  return Template.fromStack(stack);
}

test('operator pool uses email as the username and a public SRP client', () => {
  const synthesized = template();

  synthesized.hasResourceProperties('AWS::Cognito::UserPool', {
    UsernameAttributes: ['email'],
    AutoVerifiedAttributes: ['email'],
    AdminCreateUserConfig: {
      AllowAdminCreateUserOnly: true,
    },
    UserPoolTier: 'LITE',
    AccountRecoverySetting: {
      RecoveryMechanisms: [
        { Name: 'verified_email', Priority: 1 },
      ],
    },
    Policies: {
      PasswordPolicy: {
        MinimumLength: 12,
      },
    },
  });

  const pools = synthesized.findResources('AWS::Cognito::UserPool');
  expect(Object.values(pools)).toHaveLength(1);
  // A required email schema attribute conflicts with email-as-username and
  // CloudFormation rejects the pool.
  expect(Object.values(pools)[0].Properties.Schema).toBeUndefined();

  synthesized.hasResourceProperties('AWS::Cognito::UserPoolClient', {
    GenerateSecret: false,
    PreventUserExistenceErrors: 'ENABLED',
    ExplicitAuthFlows: Match.arrayWith(['ALLOW_USER_SRP_AUTH']),
    AllowedOAuthFlowsUserPoolClient: false,
  });
});

test('uploads bucket is private, encrypted, and TLS-only', () => {
  const synthesized = template();

  synthesized.hasResourceProperties('AWS::S3::Bucket', {
    BucketEncryption: {
      ServerSideEncryptionConfiguration: [
        {
          ServerSideEncryptionByDefault: {
            SSEAlgorithm: 'AES256',
          },
        },
      ],
    },
    PublicAccessBlockConfiguration: {
      BlockPublicAcls: true,
      BlockPublicPolicy: true,
      IgnorePublicAcls: true,
      RestrictPublicBuckets: true,
    },
    VersioningConfiguration: {
      Status: 'Enabled',
    },
    OwnershipControls: {
      Rules: [{ ObjectOwnership: 'BucketOwnerEnforced' }],
    },
  });

  synthesized.hasResourceProperties('AWS::S3::BucketPolicy', {
    PolicyDocument: {
      Statement: Match.arrayWith([
        Match.objectLike({
          Effect: 'Deny',
          Condition: {
            Bool: { 'aws:SecureTransport': 'false' },
          },
        }),
      ]),
    },
  });
});

test('diagnostic tables are on-demand with the keys each access pattern needs', () => {
  const synthesized = template();
  synthesized.resourceCountIs('AWS::DynamoDB::Table', 6);

  const tables = synthesized.findResources('AWS::DynamoDB::Table');

  expect(keysOf(tables, 'Satellites')).toEqual(['satelliteId']);
  expect(indexesOf(tables, 'Satellites')).toEqual({
    byOwner: ['ownerSub', 'satelliteId'],
  });

  expect(keysOf(tables, 'Uploads')).toEqual(['satelliteId', 'uploadedAtUploadId']);
  expect(indexesOf(tables, 'Uploads')).toEqual({
    byUploadId: ['uploadId'],
    byOwner: ['ownerSub', 'uploadedAtUploadId'],
  });

  expect(keysOf(tables, 'Anomalies')).toEqual(['uploadId', 'startTimeAnomalyId']);
  expect(indexesOf(tables, 'Anomalies')).toEqual({
    byAnomalyId: ['anomalyId'],
  });

  expect(keysOf(tables, 'CauseScores')).toEqual(['anomalyId', 'causeId']);
  expect(indexesOf(tables, 'CauseScores')).toEqual({
    byUpload: ['uploadId', 'anomalyIdCauseId'],
  });

  expect(keysOf(tables, 'SpaceWeatherEvents')).toEqual(['dataset', 'observedAt']);
  expect(indexesOf(tables, 'SpaceWeatherEvents')).toEqual({});

  expect(keysOf(tables, 'TleCache')).toEqual(['satelliteId', 'epoch']);
  expect(indexesOf(tables, 'TleCache')).toEqual({});

  for (const resource of Object.values(tables)) {
    const properties = resource.Properties;
    expect(properties.BillingMode).toBe('PAY_PER_REQUEST');
    expect(properties.SSESpecification).toEqual({ SSEEnabled: true });
    expect(properties.PointInTimeRecoverySpecification).toEqual({
      PointInTimeRecoveryEnabled: true,
    });
    expect(properties.DeletionProtectionEnabled).toBeUndefined();
  }
});

type CfnResources = ReturnType<Template['findResources']>;

function tableProperties(tables: CfnResources, idPrefix: string): Record<string, unknown> {
  const found = Object.entries(tables).find(([logicalId]) => logicalId.startsWith(idPrefix));
  if (!found) {
    throw new Error(`No table logical id starting with ${idPrefix}. Found ${Object.keys(tables).join(', ')}`);
  }
  return found[1].Properties as Record<string, unknown>;
}

function keysOf(tables: CfnResources, idPrefix: string): string[] {
  const schema = tableProperties(tables, idPrefix).KeySchema as Array<{ AttributeName: string; KeyType: string }>;
  return [...schema]
    .sort((left, right) => keyOrder(left.KeyType) - keyOrder(right.KeyType))
    .map((key) => key.AttributeName);
}

function indexesOf(tables: CfnResources, idPrefix: string): Record<string, string[]> {
  const indexes = tableProperties(tables, idPrefix).GlobalSecondaryIndexes as
    | Array<{ IndexName: string; KeySchema: Array<{ AttributeName: string; KeyType: string }>; Projection: { ProjectionType: string } }>
    | undefined;
  const result: Record<string, string[]> = {};
  for (const index of indexes ?? []) {
    expect(index.Projection).toEqual({ ProjectionType: 'ALL' });
    result[index.IndexName] = [...index.KeySchema]
      .sort((left, right) => keyOrder(left.KeyType) - keyOrder(right.KeyType))
      .map((key) => key.AttributeName);
  }
  return result;
}

function keyOrder(keyType: string): number {
  return keyType === 'HASH' ? 0 : 1;
}

test('hourly fetch runs from EventBridge and cannot read telemetry uploads', () => {
  const synthesized = template();

  synthesized.resourceCountIs('AWS::S3::Bucket', 2);
  synthesized.resourceCountIs('AWS::SecretsManager::Secret', 1);
  synthesized.hasResourceProperties('AWS::Events::Rule', {
    ScheduleExpression: 'rate(1 hour)',
    State: 'ENABLED',
  });
  synthesized.hasResourceProperties('AWS::Lambda::Function', {
    Runtime: 'python3.12',
    Handler: 'handler.handler',
    Timeout: 300,
    MemorySize: 256,
    Environment: {
      Variables: Match.objectLike({
        DONKI_LOOKBACK_DAYS: '7',
      }),
    },
  });

  const policies = JSON.stringify(synthesized.findResources('AWS::IAM::Policy'));
  expect(policies).toContain('secretsmanager:GetSecretValue');
  expect(policies).toContain('dynamodb:Scan');
  expect(policies).toContain('dynamodb:BatchWriteItem');
  expect(policies).not.toContain('dynamodb:DeleteItem');
  expect(policies).not.toContain('s3:DeleteObject');
  expect(policies).not.toContain('s3:GetObject*');

  const uploadsBucket = Object.entries(synthesized.findResources('AWS::S3::Bucket'))
    .find(([logicalId]) => logicalId.startsWith('UploadsBucket'));
  expect(uploadsBucket).toBeDefined();
  const uploadsRef = uploadsBucket?.[0];
  expect(policies).not.toContain(uploadsRef);
});
