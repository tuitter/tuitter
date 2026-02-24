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


ACCOUNT_ID = "390402531466"
REGION = "us-east-2"

# Existing Cognito (keep users working)
EXISTING_USER_POOL_ID = "us-east-2_xZZmUowL9"
EXISTING_APP_CLIENT_ID = "7109b3p9beveapsmr806freqnn"

# Existing ECR repo
ECR_REPO_NAME = "tuitter-endpoint-container"
ECR_TAG = "latest"


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

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --------------------------
        # VPC: isolated only, no NAT
        # --------------------------
        vpc = ec2.Vpc(
            self,
            "TuitterVpc",
            cidr="10.20.0.0/16",
            max_azs=2,  # keep cost/complexity down; change to 3 if desired
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
            ],
        )

        # --------------------------
        # VPC endpoints (no NAT)
        # --------------------------
        # S3 gateway endpoint (often required alongside ECR flows; cheap)
        vpc.add_gateway_endpoint(
            "S3Endpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
            subnets=[ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)],
        )

        # Interface endpoints (hourly cost but usually far cheaper than NAT gateway baseline)
        interface_services = [
            ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
            ec2.InterfaceVpcEndpointAwsService.ECR,
            ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
            ec2.InterfaceVpcEndpointAwsService.STS,
            ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            ec2.InterfaceVpcEndpointAwsService.KMS,
        ]

        endpoint_sg = ec2.SecurityGroup(
            self,
            "VpcEndpointSg",
            vpc=vpc,
            description="Security group for VPC interface endpoints",
            allow_all_outbound=True,
        )

        for idx, svc in enumerate(interface_services):
            vpc.add_interface_endpoint(
                f"Endpoint{idx}",
                service=svc,
                private_dns_enabled=True,
                subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
                ),
                security_groups=[endpoint_sg],
            )

        # --------------------------
        # Security groups
        # --------------------------
        db_sg = ec2.SecurityGroup(
            self,
            "DbSg",
            vpc=vpc,
            description="Postgres access for Tuitter",
            allow_all_outbound=True,
        )

        lambda_sg = ec2.SecurityGroup(
            self,
            "LambdaSg",
            vpc=vpc,
            description="Lambda SG for Tuitter",
            allow_all_outbound=True,
        )

        db_sg.add_ingress_rule(
            peer=lambda_sg,
            connection=ec2.Port.tcp(5432),
            description="Allow Lambda to Postgres",
        )

        # --------------------------
        # Secrets (do NOT hardcode DB creds)
        # --------------------------
        db_secret = secretsmanager.Secret(
            self,
            "DbSecret",
            secret_name="tuitter/postgres",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"username":"gist"}',
                generate_string_key="password",
                exclude_punctuation=True,
                password_length=32,
            ),
        )

        # --------------------------
        # RDS: new Postgres instance
        # --------------------------
        db = rds.DatabaseInstance(
            self,
            "TuitterDb",
            instance_identifier="tuitter-postgres",
            engine=rds.DatabaseInstanceEngine.postgres(
                version=rds.PostgresEngineVersion.VER_17_4
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE4_GRAVITON, ec2.InstanceSize.MICRO
            ),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            security_groups=[db_sg],
            publicly_accessible=False,
            allocated_storage=20,
            max_allocated_storage=200,
            storage_encrypted=True,
            backup_retention=Duration.days(1),
            deletion_protection=False,
            credentials=rds.Credentials.from_secret(db_secret),
            removal_policy=RemovalPolicy.DESTROY,  # dev-friendly; switch to RETAIN for real prod
            delete_automated_backups=True,
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
        # Lambda (Image) inside VPC
        # --------------------------
        fn = _lambda.DockerImageFunction(
            self,
            "TuitterApiLambda",
            function_name="tuitter-endpoint-fastapi-vpc",  # new name to avoid clobbering existing
            code=_lambda.DockerImageCode.from_ecr(
                repository=repo,
                tag=ECR_TAG,
            ),
            timeout=Duration.seconds(60),
            memory_size=1024,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            security_groups=[lambda_sg],
            environment={
                # Build DB URL at runtime (don’t embed password)
                # Your app should read these and construct a URL:
                "DB_HOST": db.db_instance_endpoint_address,
                "DB_PORT": str(db.db_instance_endpoint_port),
                "DB_NAME": "postgres",
                "DB_SECRET_NAME": db_secret.secret_name,
                "COGNITO_REGION": REGION,
                "COGNITO_USER_POOL_ID": user_pool.user_pool_id,
                "COGNITO_APP_CLIENT_ID": EXISTING_APP_CLIENT_ID,
                # Do NOT paste real secrets here:
                "GITHUB_WEBHOOK_SECRET": "SET_ME_LATER",
            },
        )

        # allow lambda to read db secret
        db_secret.grant_read(fn)

        # --------------------------
        # HTTP API Gateway v2
        # --------------------------
        http_api = apigwv2.HttpApi(
            self,
            "TuitterHttpApi",
            api_name="tuitter-http-api",
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
        CfnOutput(self, "VpcId", value=vpc.vpc_id)
        CfnOutput(self, "DbEndpoint", value=db.db_instance_endpoint_address)
        CfnOutput(self, "DbSecretName", value=db_secret.secret_name)
        CfnOutput(self, "LambdaName", value=fn.function_name)
        CfnOutput(self, "HttpApiUrl", value=http_api.api_endpoint)
        CfnOutput(self, "CognitoUserPoolId", value=EXISTING_USER_POOL_ID)
        CfnOutput(self, "CognitoAppClientId", value=EXISTING_APP_CLIENT_ID)


app = cdk.App()
TuitterNatFreeStack(
    app,
    "TuitterNatFreeStack",
    env=cdk.Environment(account=ACCOUNT_ID, region=REGION),
)
app.synth()
