import * as cdk from 'aws-cdk-lib/core';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

/**
 * Foundation for the LaunchPad satellite anomaly dashboard.
 *
 * Operators sign in with email. Telemetry files land in a private encrypted
 * bucket. Diagnosis state lives in the on-demand tables below. Scoring and
 * Bedrock are not part of this stack.
 */
export class LaunchpadStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const operators = this.operatorUserPool();
    const uploads = this.uploadsBucket();

    const satellites = this.satellitesTable();
    const uploadRecords = this.uploadsTable();
    const anomalies = this.anomaliesTable();
    const causeScores = this.causeScoresTable();
    const spaceWeather = this.spaceWeatherTable();
    const tleCache = this.tleCacheTable();

    new cdk.CfnOutput(this, 'UserPoolId', {
      value: operators.pool.userPoolId,
      description: 'Cognito user pool. Operators sign in with their email address.',
    });
    new cdk.CfnOutput(this, 'UserPoolClientId', {
      value: operators.client.userPoolClientId,
      description: 'Public app client for the web UI. It has no client secret.',
    });
    new cdk.CfnOutput(this, 'UploadsBucketName', {
      value: uploads.bucketName,
      description: 'Private bucket for telemetry uploads.',
    });
    new cdk.CfnOutput(this, 'SatellitesTableName', { value: satellites.tableName });
    new cdk.CfnOutput(this, 'UploadsTableName', { value: uploadRecords.tableName });
    new cdk.CfnOutput(this, 'AnomaliesTableName', { value: anomalies.tableName });
    new cdk.CfnOutput(this, 'CauseScoresTableName', { value: causeScores.tableName });
    new cdk.CfnOutput(this, 'SpaceWeatherEventsTableName', { value: spaceWeather.tableName });
    new cdk.CfnOutput(this, 'TleCacheTableName', { value: tleCache.tableName });
  }

  /**
   * Email is the username. Self sign-up is off: an admin creates each operator
   * so the pool is not open to the public. The web client uses SRP and stores
   * no secret.
   */
  private operatorUserPool(): { pool: cognito.UserPool; client: cognito.UserPoolClient } {
    const pool = new cognito.UserPool(this, 'Operators', {
      selfSignUpEnabled: false,
      signInAliases: { email: true },
      autoVerify: { email: true },
      // Email is the username, so Cognito already requires it. Marking email
      // required in the schema as well makes the pool fail to create.
      signInCaseSensitive: false,
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      mfa: cognito.Mfa.OFF,
      featurePlan: cognito.FeaturePlan.LITE,
      passwordPolicy: {
        minLength: 12,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
        tempPasswordValidity: cdk.Duration.days(7),
      },
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    const client = pool.addClient('WebClient', {
      generateSecret: false,
      disableOAuth: true,
      preventUserExistenceErrors: true,
      authFlows: { userSrp: true },
      accessTokenValidity: cdk.Duration.hours(1),
      idTokenValidity: cdk.Duration.hours(1),
      refreshTokenValidity: cdk.Duration.days(30),
    });

    return { pool, client };
  }

  /**
   * Telemetry files only. Public access is blocked, TLS is required, and
   * objects are encrypted with an S3-managed key. Versioning keeps a previous
   * copy if an upload is overwritten. The bucket is retained on stack delete.
   */
  private uploadsBucket(): s3.Bucket {
    return new s3.Bucket(this, 'UploadsBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      lifecycleRules: [
        {
          abortIncompleteMultipartUploadAfter: cdk.Duration.days(7),
        },
      ],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
  }

  /**
   * One item per satellite.
   *
   * GetItem on satelliteId opens a satellite.
   * Query GSI byOwner (ownerSub, satelliteId) lists the signed-in operator's
   * satellites. ownerSub is the Cognito sub, not the email.
   */
  private satellitesTable(): dynamodb.Table {
    const table = diagnosticTable(this, 'Satellites', 'satelliteId');
    table.addGlobalSecondaryIndex({
      indexName: 'byOwner',
      partitionKey: stringAttr('ownerSub'),
      sortKey: stringAttr('satelliteId'),
      projectionType: dynamodb.ProjectionType.ALL,
    });
    return table;
  }

  /**
   * One item per uploaded file.
   *
   * Sort key uploadedAtUploadId is `{ISO-8601 UTC}#{uploadId}`.
   * Query satelliteId for that satellite's uploads, newest first.
   * Query GSI byUploadId when the page or the processor has only the upload id.
   * Query GSI byOwner (ownerSub, uploadedAtUploadId) for the operator's uploads.
   */
  private uploadsTable(): dynamodb.Table {
    const table = diagnosticTable(this, 'Uploads', 'satelliteId', 'uploadedAtUploadId');
    table.addGlobalSecondaryIndex({
      indexName: 'byUploadId',
      partitionKey: stringAttr('uploadId'),
      projectionType: dynamodb.ProjectionType.ALL,
    });
    table.addGlobalSecondaryIndex({
      indexName: 'byOwner',
      partitionKey: stringAttr('ownerSub'),
      sortKey: stringAttr('uploadedAtUploadId'),
      projectionType: dynamodb.ProjectionType.ALL,
    });
    return table;
  }

  /**
   * One gap or error row from a file.
   *
   * Sort key startTimeAnomalyId is `{ISO-8601 start}#{anomalyId}`.
   * Query uploadId for the timeline, in time order.
   * Query GSI byAnomalyId to open one anomaly.
   */
  private anomaliesTable(): dynamodb.Table {
    const table = diagnosticTable(this, 'Anomalies', 'uploadId', 'startTimeAnomalyId');
    table.addGlobalSecondaryIndex({
      indexName: 'byAnomalyId',
      partitionKey: stringAttr('anomalyId'),
      projectionType: dynamodb.ProjectionType.ALL,
    });
    return table;
  }

  /**
   * One item per cause. A score is 0-100 and stands on its own; rows are never
   * resized so the set sums to 100.
   *
   * Query anomalyId to read every cause for one gap. Sort key causeId is the
   * cause name, so one anomaly has at most one row per cause.
   * Query GSI byUpload (uploadId, anomalyIdCauseId) to load every score for
   * an upload. anomalyIdCauseId is `{anomalyId}#{causeId}`.
   */
  private causeScoresTable(): dynamodb.Table {
    const table = diagnosticTable(this, 'CauseScores', 'anomalyId', 'causeId');
    table.addGlobalSecondaryIndex({
      indexName: 'byUpload',
      partitionKey: stringAttr('uploadId'),
      sortKey: stringAttr('anomalyIdCauseId'),
      projectionType: dynamodb.ProjectionType.ALL,
    });
    return table;
  }

  /**
   * Cached public space-weather samples, partitioned by dataset
   * (for example kp, dst, proton_10mev).
   *
   * Query dataset plus an observedAt range for the samples that overlap a gap.
   * Query dataset and observedAt <= gap time, newest first, limit 1, for the
   * sample in effect. observedAt is ISO-8601 UTC.
   */
  private spaceWeatherTable(): dynamodb.Table {
    return diagnosticTable(this, 'SpaceWeatherEvents', 'dataset', 'observedAt');
  }

  /**
   * Cached two-line element sets for one satellite.
   *
   * Query satelliteId, epoch descending, limit 1, for the newest cache entry.
   * Query satelliteId and epoch <= a gap time, descending, limit 1, for the
   * elements to propagate. epoch is the TLE epoch in ISO-8601 UTC.
   * One item per satellite per epoch; a repeat fetch overwrites that epoch.
   */
  private tleCacheTable(): dynamodb.Table {
    return diagnosticTable(this, 'TleCache', 'satelliteId', 'epoch');
  }
}

function stringAttr(name: string): dynamodb.Attribute {
  return { name, type: dynamodb.AttributeType.STRING };
}

/** On-demand table, encrypted with the DynamoDB-owned key, kept on stack delete. */
function diagnosticTable(
  scope: Construct,
  id: string,
  partitionKey: string,
  sortKey?: string,
): dynamodb.Table {
  return new dynamodb.Table(scope, id, {
    partitionKey: stringAttr(partitionKey),
    sortKey: sortKey === undefined ? undefined : stringAttr(sortKey),
    billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
    encryption: dynamodb.TableEncryption.AWS_MANAGED,
    pointInTimeRecoverySpecification: {
      pointInTimeRecoveryEnabled: true,
    },
    removalPolicy: cdk.RemovalPolicy.RETAIN,
  });
}
