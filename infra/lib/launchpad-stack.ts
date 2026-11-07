import * as path from 'node:path';
import * as cdk from 'aws-cdk-lib/core';
import * as apigateway from 'aws-cdk-lib/aws-apigateway';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

/**
 * Foundation for the LaunchPad satellite anomaly dashboard.
 *
 * Operators sign in with email. Telemetry files land in a private encrypted
 * bucket. An hourly Lambda archives public space-weather and TLE responses.
 * Operators request a presigned upload, and a parser records gap windows.
 * Scoring and Bedrock are not part of this stack.
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
    const rawResponses = this.rawResponsesBucket();
    const nasaSecret = this.nasaSecret();
    this.hourlyExternalFetch({ rawResponses, nasaSecret, satellites, spaceWeather, tleCache });
    const uploadApi = this.telemetryUpload({
      userPool: operators.pool,
      uploads,
      satellites,
      uploadRecords,
      anomalies,
    });

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
    new cdk.CfnOutput(this, 'ExternalRawBucketName', {
      value: rawResponses.bucketName,
      description: 'Private bucket for raw DONKI, NOAA, and CelesTrak responses.',
    });
    new cdk.CfnOutput(this, 'NasaDonkiSecretArn', {
      value: nasaSecret.secretArn,
      description: 'Secrets Manager ARN. Replace the generated value with a NASA API key.',
    });
    new cdk.CfnOutput(this, 'UploadApiUrl', {
      value: uploadApi.url,
      description: 'POST {url}uploads with a Cognito ID token to receive a presigned upload.',
    });
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
   * copy if an upload is overwritten. Object-created events are published so
   * the parser can run. The bucket is retained on stack delete.
   */
  private uploadsBucket(): s3.Bucket {
    return new s3.Bucket(this, 'UploadsBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      eventBridgeEnabled: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      cors: [
        {
          allowedMethods: [s3.HttpMethods.POST, s3.HttpMethods.PUT, s3.HttpMethods.HEAD],
          allowedOrigins: ['*'],
          allowedHeaders: ['*'],
          exposedHeaders: ['ETag'],
          maxAge: 3000,
        },
      ],
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
   * sample in effect.
   *
   * NOAA rows store a plain ISO-8601 UTC timestamp. DONKI rows store
   * `{timestamp}#{eventId}` so two events at the same second both remain.
   * A range end of `{end}~` includes those ids, because `~` sorts after `#`.
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

  /**
   * Raw public API bodies. Separate from the telemetry bucket so this data
   * and operator uploads are not mixed, and so the fetch role never receives
   * permission to read uploads. `raw/` expires after 30 days. `cache/` stays.
   */
  private rawResponsesBucket(): s3.Bucket {
    return new s3.Bucket(this, 'ExternalRawBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      versioned: true,
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      lifecycleRules: [
        {
          prefix: 'raw/',
          expiration: cdk.Duration.days(30),
        },
        {
          abortIncompleteMultipartUploadAfter: cdk.Duration.days(7),
        },
      ],
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
  }

  /**
   * The value is generated on first create. Put the real NASA key in with
   * `put-secret-value` after deploy. Later deploys do not rotate it.
   */
  private nasaSecret(): secretsmanager.Secret {
    return new secretsmanager.Secret(this, 'NasaDonkiApiKey', {
      description: 'NASA API key for the hourly DONKI fetch. Replace the generated value after the first deploy.',
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
  }

  /**
   * Hourly fetch. The role can read the NASA secret, scan Satellites for
   * catalog numbers, and write space-weather and TLE rows. It can get and put
   * objects under raw/ and cache/ in the external bucket only.
   */
  private hourlyExternalFetch(resources: {
    rawResponses: s3.Bucket;
    nasaSecret: secretsmanager.Secret;
    satellites: dynamodb.Table;
    spaceWeather: dynamodb.Table;
    tleCache: dynamodb.Table;
  }): void {
    const backendSrc = path.resolve(__dirname, '../../backend/src');
    const fetchFn = new lambda.Function(this, 'ExternalFetch', {
      description: 'Hourly fetch of DONKI, NOAA SWPC, and CelesTrak into S3 and DynamoDB.',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'handler.handler',
      code: lambda.Code.fromAsset(backendSrc, {
        exclude: ['**/__pycache__/**', '**/*.pyc'],
      }),
      timeout: cdk.Duration.minutes(5),
      memorySize: 256,
      logGroup: new logs.LogGroup(this, 'ExternalFetchLogs', {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
      environment: {
        RAW_BUCKET_NAME: resources.rawResponses.bucketName,
        SPACE_WEATHER_TABLE_NAME: resources.spaceWeather.tableName,
        TLE_TABLE_NAME: resources.tleCache.tableName,
        SATELLITES_TABLE_NAME: resources.satellites.tableName,
        NASA_SECRET_ARN: resources.nasaSecret.secretArn,
        DONKI_LOOKBACK_DAYS: '7',
      },
    });

    fetchFn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'ReadWriteExternalRaw',
      actions: ['s3:GetObject', 's3:PutObject'],
      resources: [
        resources.rawResponses.arnForObjects('raw/*'),
        resources.rawResponses.arnForObjects('cache/*'),
      ],
    }));
    fetchFn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'WriteSpaceWeatherAndTle',
      actions: ['dynamodb:PutItem', 'dynamodb:BatchWriteItem'],
      resources: [resources.spaceWeather.tableArn, resources.tleCache.tableArn],
    }));
    fetchFn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'ListTrackedSatellites',
      actions: ['dynamodb:Scan'],
      resources: [resources.satellites.tableArn],
    }));
    resources.nasaSecret.grantRead(fetchFn);

    new events.Rule(this, 'HourlyExternalFetch', {
      description: 'Fetch space weather and TLEs every hour.',
      schedule: events.Schedule.rate(cdk.Duration.hours(1)),
      targets: [new targets.LambdaFunction(fetchFn)],
    });
  }

  /**
   * Presigned POST for one telemetry file, then a parser on the S3 event.
   * The presign role can write the pending upload row and sign PutObject.
   * The parser role can read that object and write anomaly windows.
   * Neither role can delete objects or read the external-data bucket.
   */
  private telemetryUpload(resources: {
    userPool: cognito.UserPool;
    uploads: s3.Bucket;
    satellites: dynamodb.Table;
    uploadRecords: dynamodb.Table;
    anomalies: dynamodb.Table;
  }): apigateway.RestApi {
    const backendSrc = path.resolve(__dirname, '../../backend/src');
    const code = lambda.Code.fromAsset(backendSrc, {
      exclude: ['**/__pycache__/**', '**/*.pyc'],
    });
    const presignFn = new lambda.Function(this, 'PresignUpload', {
      description: 'Returns a presigned POST for one telemetry file.',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'presign.handler',
      code,
      timeout: cdk.Duration.seconds(10),
      memorySize: 256,
      logGroup: new logs.LogGroup(this, 'PresignUploadLogs', {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
      environment: {
        UPLOADS_BUCKET_NAME: resources.uploads.bucketName,
        UPLOADS_TABLE_NAME: resources.uploadRecords.tableName,
        SATELLITES_TABLE_NAME: resources.satellites.tableName,
        MAX_UPLOAD_BYTES: '5242880',
        PRESIGN_EXPIRES_SECONDS: '900',
      },
    });
    const parserFn = new lambda.Function(this, 'ParseUpload', {
      description: 'Validates an uploaded telemetry file and records gap windows.',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'parse_upload.handler',
      code,
      timeout: cdk.Duration.seconds(60),
      memorySize: 512,
      logGroup: new logs.LogGroup(this, 'ParseUploadLogs', {
        retention: logs.RetentionDays.ONE_WEEK,
        removalPolicy: cdk.RemovalPolicy.DESTROY,
      }),
      environment: {
        UPLOADS_BUCKET_NAME: resources.uploads.bucketName,
        UPLOADS_TABLE_NAME: resources.uploadRecords.tableName,
        ANOMALIES_TABLE_NAME: resources.anomalies.tableName,
        MAX_UPLOAD_BYTES: '5242880',
        MAX_UPLOAD_ROWS: '100000',
        GAP_INTERVAL_MULTIPLIER: '2',
      },
    });

    presignFn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'SignTelemetryUpload',
      actions: ['s3:PutObject'],
      resources: [resources.uploads.arnForObjects('uploads/*')],
    }));
    presignFn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'ReadSatelliteOwner',
      actions: ['dynamodb:GetItem'],
      resources: [resources.satellites.tableArn],
    }));
    presignFn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'CreatePendingUpload',
      actions: ['dynamodb:PutItem'],
      resources: [resources.uploadRecords.tableArn],
    }));

    parserFn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'ReadTelemetryUpload',
      actions: ['s3:GetObject'],
      resources: [resources.uploads.arnForObjects('uploads/*')],
    }));
    parserFn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'UpdateUploadStatus',
      actions: ['dynamodb:GetItem', 'dynamodb:UpdateItem'],
      resources: [resources.uploadRecords.tableArn],
    }));
    parserFn.addToRolePolicy(new iam.PolicyStatement({
      sid: 'WriteAnomalyWindows',
      actions: ['dynamodb:PutItem', 'dynamodb:BatchWriteItem'],
      resources: [resources.anomalies.tableArn],
    }));

    const api = new apigateway.RestApi(this, 'UploadApi', {
      restApiName: 'launchpad-uploads',
      description: 'Presigned telemetry uploads for signed-in operators.',
      defaultCorsPreflightOptions: {
        allowOrigins: apigateway.Cors.ALL_ORIGINS,
        allowMethods: ['POST', 'OPTIONS'],
        allowHeaders: ['Authorization', 'Content-Type'],
      },
      deployOptions: {
        throttlingRateLimit: 10,
        throttlingBurstLimit: 20,
      },
    });
    const authorizer = new apigateway.CognitoUserPoolsAuthorizer(this, 'OperatorsAuthorizer', {
      cognitoUserPools: [resources.userPool],
    });
    api.root.addResource('uploads').addMethod(
      'POST',
      new apigateway.LambdaIntegration(presignFn, { proxy: true }),
      {
        authorizer,
        authorizationType: apigateway.AuthorizationType.COGNITO,
      },
    );

    new events.Rule(this, 'TelemetryUploadCreated', {
      description: 'Parse a telemetry file after it is created in the uploads bucket.',
      eventPattern: {
        source: ['aws.s3'],
        detailType: ['Object Created'],
        detail: {
          bucket: { name: [resources.uploads.bucketName] },
          object: { key: [{ prefix: 'uploads/' }] },
        },
      },
      targets: [new targets.LambdaFunction(parserFn, { retryAttempts: 2 })],
    });
    return api;
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
