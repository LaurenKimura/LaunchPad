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

  const policies = synthesized.findResources('AWS::IAM::Policy');
  const allPolicies = JSON.stringify(policies);
  expect(allPolicies).toContain('secretsmanager:GetSecretValue');
  expect(allPolicies).toContain('dynamodb:BatchWriteItem');
  expect(allPolicies).not.toContain('dynamodb:DeleteItem');
  expect(allPolicies).not.toContain('s3:DeleteObject');
  expect(allPolicies).not.toContain('s3:GetObject*');

  const fetchPolicy = Object.entries(policies).find(([logicalId]) => logicalId.startsWith('ExternalFetch'));
  expect(fetchPolicy).toBeDefined();
  const fetchJson = JSON.stringify(fetchPolicy?.[1]);
  expect(fetchJson).toContain('dynamodb:Scan');
  expect(fetchJson).not.toContain('UploadsBucket');
});

test('upload API signs a post and the parser reads only the uploads prefix', () => {
  const synthesized = template();

  synthesized.resourceCountIs('AWS::Events::Rule', 2);
  synthesized.hasResourceProperties('AWS::ApiGateway::Method', {
    HttpMethod: 'POST',
    AuthorizationType: 'COGNITO_USER_POOLS',
  });
  synthesized.hasResourceProperties('AWS::Lambda::Function', {
    Handler: 'presign.handler',
    Timeout: 10,
    Environment: {
      Variables: Match.objectLike({
        MAX_UPLOAD_BYTES: '5242880',
        PRESIGN_EXPIRES_SECONDS: '900',
      }),
    },
  });
  synthesized.hasResourceProperties('AWS::Lambda::Function', {
    Handler: 'parse_upload.handler',
    Timeout: 60,
    MemorySize: 512,
    Environment: {
      Variables: Match.objectLike({
        GAP_INTERVAL_MULTIPLIER: '2',
        MAX_UPLOAD_ROWS: '100000',
      }),
    },
  });
  synthesized.hasResourceProperties('Custom::S3BucketNotifications', {
    NotificationConfiguration: {
      EventBridgeConfiguration: {},
    },
  });
  synthesized.hasResourceProperties('AWS::Events::Rule', {
    EventPattern: Match.objectLike({
      source: ['aws.s3'],
      'detail-type': ['Object Created'],
    }),
  });

  const rules = JSON.stringify(synthesized.findResources('AWS::Events::Rule'));
  expect(rules).toContain('uploads/');

  const policies = synthesized.findResources('AWS::IAM::Policy');
  const presign = JSON.stringify(Object.entries(policies).find(([id]) => id.startsWith('PresignUpload'))?.[1]);
  const parser = JSON.stringify(Object.entries(policies).find(([id]) => id.startsWith('ParseUpload'))?.[1]);
  expect(presign).toContain('s3:PutObject');
  expect(presign).not.toContain('s3:GetObject');
  expect(parser).toContain('s3:GetObject');
  expect(parser).toContain('dynamodb:UpdateItem');
  expect(parser).not.toContain('s3:PutObject');
  expect(presign).toContain('uploads/*');
  expect(parser).toContain('uploads/*');
});
