#!/usr/bin/env python3
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_lambda as _lambda,
    aws_ecr as ecr,
    aws_apigatewayv2 as apigwv2,
    aws_apigatewayv2_integrations as apigwv2_integrations,
    aws_cognito as cognito,
    aws_secretsmanager as secretsmanager,
)
from constructs import Construct
import os


ACCOUNT_ID = "390402531466"
REGION = "us-east-2"

# Existing Cognito (keep users working)
EXISTING_USER_POOL_ID = "us-east-2_xZZmUowL9"
EXISTING_APP_CLIENT_ID = "7109b3p9beveapsmr806freqnn"

# Existing ECR repo
ECR_REPO_NAME = "tuitter-endpoint-container"
PROD_ECR_TAG = "prod-latest"
DEV_ECR_TAG = "dev-latest"


class TuitterNatFreeStack(Stack):
    """
    NAT-free, CDK-managed stack:

    - New VPC (isolated subnets only; no NAT)
    - VPC endpoints for: CloudWatch Logs, ECR API/DKR, STS, Secrets Manager, KMS + S3 gateway
    - New RDS Postgres 17.4 (private)
    - Lambda (Docker image from existing ECR repo) inside VPC
    - HTTP API Gateway v2: ANY /{proxy+} -> Lambda
    - References existing Cognito pool/client (no user migration)
    """

    def __init__(self, scope: Construct, construct_id: str, *, is_dev: bool = False, ecr_tag: str | None = None, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if ecr_tag is None:
            ecr_tag = DEV_ECR_TAG if is_dev else PROD_ECR_TAG

        # Migration mode controls whether the Lambda performs a one-time Alembic
        # stamp/upgrade on startup. Default is "none" so app startups do not mutate schema.
        migration_mode = self.node.try_get_context("migration-mode") or os.environ.get("CDK_MIGRATION_MODE") or "none"

        # --------------------------
        # Aggressive mode: do NOT create a custom VPC or VPC endpoints.
        # Use the account's default VPC for RDS so we avoid creating
        # interface/gateway endpoints and their hourly costs.
        # --------------------------
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)
        # --------------------------
        # Aggressive RDS: create in the default VPC and make publicly accessible
        # to avoid maintaining custom subnets and endpoint costs. This is
        # insecure but minimizes the number of managed resources.
        # --------------------------
        db = rds.DatabaseInstance(
            self,
            "TuitterDb",
            instance_identifier=("tuitter-postgres-dev" if is_dev else "tuitter-postgres"),
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_17_4
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.MICRO
            ),
            vpc=vpc,
            # Place in public subnets so the instance has a public endpoint
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            publicly_accessible=True,
            allocated_storage=(10 if is_dev else 20),
            max_allocated_storage=200,
            storage_encrypted=False,
            backup_retention=Duration.days(7) if not is_dev else Duration.days(1),
            deletion_protection=(not is_dev),
            credentials=rds.Credentials.from_password(
                "postgres", cdk.SecretValue.plain_text("postgres")
            ),
            removal_policy=(RemovalPolicy.DESTROY if is_dev else RemovalPolicy.RETAIN),
            delete_automated_backups=False,
        )

        # --------------------------
        # Cognito: reference existing pool/client
        # --------------------------
        user_pool = cognito.UserPool.from_user_pool_id(
            self, "ExistingUserPool", EXISTING_USER_POOL_ID
        )

        # --------------------------
        # ECR: reference existing repo
        # --------------------------
        repo = ecr.Repository.from_repository_name(self, "TuitterRepo", ECR_REPO_NAME)

        # --------------------------
        # Secrets Manager: reference pre-created secrets
        # --------------------------
        db_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "DbSecret", "tuitter/db-password"
        )
        r2_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "R2Secret", "tuitter/r2-credentials"
        )

        # --------------------------
        # Lambda (Image) outside VPC (default internet egress)
        # --------------------------
        fn = _lambda.DockerImageFunction(
            self,
            "TuitterApiLambda",
            function_name=("tuitter-api-dev" if is_dev else "tuitter-api"),
            code=_lambda.DockerImageCode.from_ecr(
                repository=repo,
                tag=ecr_tag,
            ),
            timeout=Duration.seconds(60),
            memory_size=1024,
            # Run the Lambda without VPC configuration so it has internet
            # egress by default and can reach Cognito and the public RDS
            # endpoint without requiring NAT or VPC endpoints.
            environment={
                # DB connection — DATABASE_URL constructed in backend from parts
                "DATABASE_URL": cdk.Fn.join(
                    "",
                    [
                        "postgresql://postgres:",
                        db_secret.secret_value.to_string(),
                        "@",
                        db.db_instance_endpoint_address,
                        ":",
                        str(db.db_instance_endpoint_port),
                        "/postgres?sslmode=require",
                    ],
                ),
                "DB_HOST": db.db_instance_endpoint_address,
                "DB_PORT": str(db.db_instance_endpoint_port),
                "DB_NAME": "postgres",
                "DB_USER": "postgres",
                "DB_PASSWORD": db_secret.secret_value.to_string(),
                "DB_SSLMODE": "require",
                "COGNITO_REGION": REGION,
                "COGNITO_USER_POOL_ID": user_pool.user_pool_id,
                "COGNITO_APP_CLIENT_ID": EXISTING_APP_CLIENT_ID,
                # Cloudflare R2 image storage
                "R2_ACCOUNT_ID": "e9c7eba4bcbb730642c1e557f8144520",
                "R2_ACCESS_KEY_ID": r2_secret.secret_value_from_json("access_key_id").to_string(),
                "R2_SECRET_ACCESS_KEY": r2_secret.secret_value_from_json("secret_access_key").to_string(),
                "R2_BUCKET_NAME": "tuitter-images",
                "R2_PUBLIC_URL": "https://pub-77dc0778b6d6493c95fb6f6bb1cf56e2.r2.dev",
                "RUN_MIGRATIONS_MODE": migration_mode,
            },
        )

        # Grant Lambda read access to each secret
        db_secret.grant_read(fn)
        r2_secret.grant_read(fn)

        # Make the DB publicly accessible and allow connections from anywhere
        # (aggressive / insecure but minimizes infra). This makes the DB
        # reachable by the Lambda running outside the VPC.
        try:
            db.connections.allow_default_port_from_any_ipv4(
                description="Allow public access (aggressive)"
            )
        except Exception:
            pass

        # --------------------------
        # HTTP API Gateway v2
        # --------------------------
        http_api = apigwv2.HttpApi(
            self,
            "TuitterHttpApi",
            api_name=("tuitter-http-api-dev" if is_dev else "tuitter-http-api"),
        )

        integration = apigwv2_integrations.HttpLambdaIntegration(
            "LambdaIntegration",
            handler=fn,
        )

        http_api.add_routes(
            path="/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=integration,
        )

        # --------------------------
        # Outputs
        # --------------------------
        # Note: VPC is the account default VPC (not created by this stack)
        try:
            CfnOutput(self, "VpcId", value=vpc.vpc_id)
        except Exception:
            # from_lookup may not expose vpc_id during synth in some contexts
            pass

        CfnOutput(self, "DbEndpoint", value=db.db_instance_endpoint_address)
        CfnOutput(self, "LambdaName", value=fn.function_name)
        CfnOutput(self, "HttpApiUrl", value=http_api.api_endpoint)
        CfnOutput(self, "CognitoUserPoolId", value=EXISTING_USER_POOL_ID)
        CfnOutput(self, "CognitoAppClientId", value=EXISTING_APP_CLIENT_ID)


app = cdk.App()

# stage selection: prefer CDK context 'stage', fallback to env var 'CDK_STAGE'
stage = app.node.try_get_context("stage") or os.environ.get("CDK_STAGE", "prod")

if stage == "dev":
    TuitterNatFreeStack(
        app,
        "TuitterNatFreeStack-Dev",
        env=cdk.Environment(account=ACCOUNT_ID, region=REGION),
        is_dev=True,
        ecr_tag=app.node.try_get_context("image-tag") or os.environ.get("CDK_IMAGE_TAG") or DEV_ECR_TAG,
    )
else:
    TuitterNatFreeStack(
        app,
        "TuitterNatFreeStack",
        env=cdk.Environment(account=ACCOUNT_ID, region=REGION),
        is_dev=False,
        ecr_tag=app.node.try_get_context("image-tag") or os.environ.get("CDK_IMAGE_TAG") or PROD_ECR_TAG,
    )

app.synth()
