"""Deploy the ClaimSense frontend to AWS: the adjuster console + the orchestrator (M4, D-049; Submission 2's
"deployed frontend URL").

    python M4/cloud/frontend.py apply      # needs `aws login` and Docker; ~10-15 min the first time (CloudFront)
    python M4/cloud/frontend.py status
    python M4/cloud/frontend.py destroy    # removes everything this script created (keeps ECR images)

Shape (the M1 reference architecture's "Orchestrator + console on ECS Fargate"):
  CloudFront (HTTPS on *.cloudfront.net, WebSockets) -> internet-facing ALB (accepts CloudFront only: the AWS-managed
  origin-facing prefix list) -> ONE Fargate task with two containers:
     console       Streamlit :8501, the only thing the ALB reaches; demo sign-in mode (passcode + synthetic users)
     orchestrator  :8003 on localhost inside the task; agents reach data only through the governed door (MCP + OBO)
  The orchestrator reads the OpenAI key from Secrets Manager at runtime, verifies Cognito ID tokens, writes audit rows
  to the DynamoDB trail and metrics to CloudWatch. ~$35-40/month while running (ALB ~$16, task 1 vCPU/2 GB ~$20).

Secrets: the demo passcode is generated here, stored only as a SHA-256 hash in Secrets Manager
(`claimsense/demo-signin`, with the five synthetic users' Cognito passwords) and in ~/.claimsense/demo.json (0600)
for the owner to put in the submission form. Nothing secret is printed, committed or baked into an image.
"""
import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
ROOT = Path(__file__).resolve().parents[2]
CONF = Path.home() / ".claimsense"
N = "claimsense-frontend"
CLUSTER, LOGS, DEMO_SECRET, OPENAI_SECRET = "claimsense", "/claimsense/frontend", "claimsense/demo-signin", "claimsense/openai-api-key"
TAGS = [{"Key": "Project", "Value": "ClaimSense"}]
CACHING_DISABLED, ALL_VIEWER = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad", "216adef6-5c7f-47e4-b989-5492eafa07d3"

aws = lambda svc: boto3.client(svc, region_name=REGION)
say = lambda m: print(f"\n==> {m}", flush=True)


def tag_of_head():
    tag = subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip()
    return tag + ("-dirty" if dirty else "")


def images(account, tag):
    ecr = aws("ecr")
    for repo in ("claimsense/orchestrator", "claimsense/console"):
        try:
            ecr.describe_repositories(repositoryNames=[repo])
        except ecr.exceptions.RepositoryNotFoundException:
            ecr.create_repository(repositoryName=repo, imageTagMutability="IMMUTABLE",
                                  imageScanningConfiguration={"scanOnPush": True}, tags=TAGS)
    auth = ecr.get_authorization_token()["authorizationData"][0]
    user, pw = base64.b64decode(auth["authorizationToken"]).decode().split(":", 1)
    registry = auth["proxyEndpoint"].replace("https://", "")
    subprocess.run(["docker", "login", "-u", user, "--password-stdin", registry], input=pw, text=True, check=True,
                   stdout=subprocess.DEVNULL)
    out = {}
    try:
        for name, dockerfile in (("orchestrator", "M2/services/orchestrator/Dockerfile"),
                                 ("console", "M2/services/console/Dockerfile")):
            ref = f"{registry}/claimsense/{name}:{tag}"
            exists = ecr.batch_get_image(repositoryName=f"claimsense/{name}", imageIds=[{"imageTag": tag}])["images"]
            if not exists:
                subprocess.run(["docker", "build", "--provenance=false", "--platform", "linux/amd64", "-f", dockerfile,
                                "-t", ref, str(ROOT)], check=True, stdout=subprocess.DEVNULL)
                subprocess.run(["docker", "push", ref], check=True, stdout=subprocess.DEVNULL)
            out[name] = ref
            print(f"image claimsense/{name}:{tag}")
    finally:
        subprocess.run(["docker", "logout", registry], check=False, stdout=subprocess.DEVNULL)
    return out


def demo_secret():
    cog = json.loads((CONF / "cognito.json").read_text())
    demo_path = CONF / "demo.json"
    if demo_path.exists():
        passcode = json.loads(demo_path.read_text())["passcode"]
    else:
        alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"       # no look-alikes (I l 1 O 0) and no punctuation
        passcode = "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))
        fd = os.open(demo_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"passcode": passcode, "note": "demo sign-in passcode for the deployed ClaimSense console"}, f)
    value = json.dumps({"passcode_sha256": hashlib.sha256(passcode.encode()).hexdigest(), "pool_id": cog["pool_id"],
                        "client_id": cog["client_id"], "users": cog["passwords"]})
    sm = aws("secretsmanager")
    try:
        arn = sm.create_secret(Name=DEMO_SECRET, SecretString=value, Tags=TAGS)["ARN"]
    except sm.exceptions.ResourceExistsException:
        arn = sm.put_secret_value(SecretId=DEMO_SECRET, SecretString=value)["ARN"]
    print(f"secret {DEMO_SECRET}: passcode hash + synthetic users' passwords (passcode in ~/.claimsense/demo.json)")
    return arn, cog


def role(name, trust_service, policy=None, managed=None):
    iam = aws("iam")
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": trust_service},
                                                     "Action": "sts:AssumeRole"}]}
    try:
        arn = iam.get_role(RoleName=name)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(RoleName=name, AssumeRolePolicyDocument=json.dumps(trust), Tags=TAGS)["Role"]["Arn"]
    if managed:
        iam.attach_role_policy(RoleName=name, PolicyArn=managed)
    if policy:
        iam.put_role_policy(RoleName=name, PolicyName="least-privilege", PolicyDocument=json.dumps(policy))
    return arn


def network():
    ec2 = aws("ec2")
    vpc = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"][0]["VpcId"]
    subnets = [s["SubnetId"] for s in ec2.describe_subnets(Filters=[{"Name": "vpc-id", "Values": [vpc]},
                                                                      {"Name": "default-for-az", "Values": ["true"]}])["Subnets"]]

    def sg(name, desc):
        found = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [name]}, {"Name": "vpc-id", "Values": [vpc]}])["SecurityGroups"]
        return found[0]["GroupId"] if found else ec2.create_security_group(GroupName=name, Description=desc, VpcId=vpc)["GroupId"]
    alb_sg, task_sg = sg(f"{N}-alb", "ClaimSense ALB: CloudFront only"), sg(f"{N}-task", "ClaimSense task: ALB only")
    pl = ec2.describe_managed_prefix_lists(Filters=[{"Name": "prefix-list-name",
                                                     "Values": ["com.amazonaws.global.cloudfront.origin-facing"]}])["PrefixLists"][0]["PrefixListId"]
    for gid, perm in ((alb_sg, {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "PrefixListIds": [{"PrefixListId": pl}]}),
                      (task_sg, {"IpProtocol": "tcp", "FromPort": 8501, "ToPort": 8501, "UserIdGroupPairs": [{"GroupId": alb_sg}]})):
        try:
            ec2.authorize_security_group_ingress(GroupId=gid, IpPermissions=[perm])
        except ec2.exceptions.ClientError as e:
            if "Duplicate" not in str(e):
                raise
    return vpc, subnets, alb_sg, task_sg


def load_balancer(vpc, subnets, alb_sg):
    elb = aws("elbv2")
    try:
        alb = elb.describe_load_balancers(Names=[N])["LoadBalancers"][0]
    except elb.exceptions.LoadBalancerNotFoundException:
        alb = elb.create_load_balancer(Name=N, Subnets=subnets, SecurityGroups=[alb_sg], Scheme="internet-facing",
                                       Type="application", Tags=TAGS)["LoadBalancers"][0]
    elb.modify_load_balancer_attributes(LoadBalancerArn=alb["LoadBalancerArn"],
                                        Attributes=[{"Key": "idle_timeout.timeout_seconds", "Value": "300"}])
    try:
        tg = elb.describe_target_groups(Names=[f"{N}-console"])["TargetGroups"][0]
    except elb.exceptions.TargetGroupNotFoundException:
        tg = elb.create_target_group(Name=f"{N}-console", Protocol="HTTP", Port=8501, VpcId=vpc, TargetType="ip",
                                     HealthCheckPath="/_stcore/health", HealthCheckIntervalSeconds=15,
                                     HealthyThresholdCount=2, Tags=TAGS)["TargetGroups"][0]
    elb.modify_target_group_attributes(TargetGroupArn=tg["TargetGroupArn"], Attributes=[
        {"Key": "stickiness.enabled", "Value": "true"}, {"Key": "stickiness.type", "Value": "lb_cookie"},
        {"Key": "deregistration_delay.timeout_seconds", "Value": "15"}])
    if not elb.describe_listeners(LoadBalancerArn=alb["LoadBalancerArn"])["Listeners"]:
        elb.create_listener(LoadBalancerArn=alb["LoadBalancerArn"], Protocol="HTTP", Port=80,
                            DefaultActions=[{"Type": "forward", "TargetGroupArn": tg["TargetGroupArn"]}])
    return alb, tg


def task_and_service(imgs, account, door, cog, subnets, task_sg, tg, exec_arn, task_arn):
    ecs, logs = aws("ecs"), aws("logs")
    try:
        logs.create_log_group(logGroupName=LOGS, tags={"Project": "ClaimSense"})
        logs.put_retention_policy(logGroupName=LOGS, retentionInDays=30)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    if not ecs.describe_clusters(clusters=[CLUSTER])["clusters"] or \
            ecs.describe_clusters(clusters=[CLUSTER])["clusters"][0]["status"] != "ACTIVE":
        ecs.create_cluster(clusterName=CLUSTER, tags=[{"key": "Project", "value": "ClaimSense"}])
    issuer = f"https://cognito-idp.{REGION}.amazonaws.com/{cog['pool_id']}"
    log = lambda p: {"logDriver": "awslogs", "options": {"awslogs-group": LOGS, "awslogs-region": REGION, "awslogs-stream-prefix": p}}
    env = lambda d: [{"name": k, "value": v} for k, v in d.items()]
    td = ecs.register_task_definition(
        family=N, networkMode="awsvpc", requiresCompatibilities=["FARGATE"], cpu="1024", memory="2048",
        executionRoleArn=exec_arn, taskRoleArn=task_arn, runtimePlatform={"cpuArchitecture": "X86_64", "operatingSystemFamily": "LINUX"},
        containerDefinitions=[
            {"name": "orchestrator", "image": imgs["orchestrator"], "essential": True, "logConfiguration": log("orchestrator"),
             "portMappings": [{"containerPort": 8003}],
             "environment": env({"COGNITO_JWKS_URL": f"{issuer}/.well-known/jwks.json", "CLAIMSENSE_JWT_ISSUER": issuer,
                                 "CLAIMSENSE_JWT_AUDIENCE": cog["client_id"], "BOUNDARY_URL": door,
                                 "CLAIMSENSE_MCP_URL": f"{door}/mcp", "OPENAI_SECRET_ID": OPENAI_SECRET, "MOCK_BRAIN": "0",
                                 "CLAIMSENSE_DEMO_SECRET_ID": DEMO_SECRET, "CLAIMSENSE_METRICS": "cloudwatch",
                                 "CLAIMSENSE_AUDIT_TABLE": "claimsense-audit", "AWS_REGION": REGION,
                                 "AWS_DEFAULT_REGION": REGION}),
             "healthCheck": {"command": ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8003/healthz')\""],
                             "interval": 15, "timeout": 5, "retries": 4, "startPeriod": 30}},
            {"name": "console", "image": imgs["console"], "essential": True, "logConfiguration": log("console"),
             "portMappings": [{"containerPort": 8501}],
             "environment": env({"ORCHESTRATOR_URL": "http://localhost:8003", "BOUNDARY_URL": door,
                                 "CLAIMSENSE_DEMO_SIGNIN": "1"}),
             "dependsOn": [{"containerName": "orchestrator", "condition": "HEALTHY"}]}],
        tags=[{"key": "Project", "value": "ClaimSense"}])["taskDefinition"]["taskDefinitionArn"]
    svc = ecs.describe_services(cluster=CLUSTER, services=[N])["services"]
    net = {"awsvpcConfiguration": {"subnets": subnets, "securityGroups": [task_sg], "assignPublicIp": "ENABLED"}}
    if svc and svc[0]["status"] == "ACTIVE":
        ecs.update_service(cluster=CLUSTER, service=N, taskDefinition=td, desiredCount=1, networkConfiguration=net,
                           forceNewDeployment=True)
    else:
        ecs.create_service(cluster=CLUSTER, serviceName=N, taskDefinition=td, desiredCount=1, launchType="FARGATE",
                           networkConfiguration=net, healthCheckGracePeriodSeconds=120,
                           loadBalancers=[{"targetGroupArn": tg["TargetGroupArn"], "containerName": "console", "containerPort": 8501}],
                           tags=[{"key": "Project", "value": "ClaimSense"}])
    print("waiting for the service to be stable (task running and healthy behind the ALB)...", flush=True)
    ecs.get_waiter("services_stable").wait(cluster=CLUSTER, services=[N], WaiterConfig={"Delay": 15, "MaxAttempts": 60})
    return td


def cloudfront(alb_dns):
    cf = aws("cloudfront")
    for d in cf.list_distributions().get("DistributionList", {}).get("Items", []) or []:
        if d.get("Comment") == N:
            return d["DomainName"], d["Id"]
    d = cf.create_distribution_with_tags(DistributionConfigWithTags={"DistributionConfig": {
        "CallerReference": f"{N}-{int(time.time())}", "Comment": N, "Enabled": True, "PriceClass": "PriceClass_100",
        "Origins": {"Quantity": 1, "Items": [{"Id": "alb", "DomainName": alb_dns, "CustomOriginConfig": {
            "HTTPPort": 80, "HTTPSPort": 443, "OriginProtocolPolicy": "http-only", "OriginReadTimeout": 60,
            "OriginKeepaliveTimeout": 60}}]},
        "DefaultCacheBehavior": {"TargetOriginId": "alb", "ViewerProtocolPolicy": "redirect-to-https", "Compress": True,
                                 "CachePolicyId": CACHING_DISABLED, "OriginRequestPolicyId": ALL_VIEWER,
                                 "AllowedMethods": {"Quantity": 7, "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
                                                    "CachedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]}}}},
        "Tags": {"Items": TAGS}})["Distribution"]
    print("waiting for CloudFront to deploy (usually 5-10 minutes)...", flush=True)
    cf.get_waiter("distribution_deployed").wait(Id=d["Id"], WaiterConfig={"Delay": 30, "MaxAttempts": 60})
    return d["DomainName"], d["Id"]


def apply():
    account = aws("sts").get_caller_identity()["Account"]
    tag = tag_of_head()
    if tag.endswith("-dirty"):
        sys.exit("refusing to deploy a dirty tree: commit first (the image tag must name a commit)")
    door = json.loads((CONF / "deploy.json").read_text())["door_url"]
    say(f"images (linux/amd64) for commit {tag}")
    imgs = images(account, tag)
    say("Secrets Manager: demo sign-in")
    demo_arn, cog = demo_secret()
    say("IAM: task execution role + task role (least privilege)")
    sm = aws("secretsmanager")
    openai_arn = sm.describe_secret(SecretId=OPENAI_SECRET)["ARN"]
    exec_arn = role(f"{N}-exec", "ecs-tasks.amazonaws.com",
                    managed="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy")
    task_arn = role(f"{N}-task", "ecs-tasks.amazonaws.com", policy={"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": "secretsmanager:GetSecretValue", "Resource": [openai_arn, demo_arn]},
        {"Effect": "Allow", "Action": "cognito-idp:AdminInitiateAuth",
         "Resource": f"arn:aws:cognito-idp:{REGION}:{account}:userpool/{cog['pool_id']}"},
        {"Effect": "Allow", "Action": ["dynamodb:PutItem", "dynamodb:Scan"],
         "Resource": f"arn:aws:dynamodb:{REGION}:{account}:table/claimsense-audit"},
        {"Effect": "Allow", "Action": "cloudwatch:PutMetricData", "Resource": "*",
         "Condition": {"StringEquals": {"cloudwatch:namespace": "ClaimSense"}}}]})
    time.sleep(10)                                         # let IAM propagate before ECS assumes the roles
    say("network: default VPC, ALB (CloudFront-only ingress) and task security groups")
    vpc, subnets, alb_sg, task_sg = network()
    say("Application Load Balancer + target group (console :8501, sticky, WebSockets)")
    alb, tg = load_balancer(vpc, subnets, alb_sg)
    say("ECS service-linked role (created once per account; a fresh account has none)")
    try:
        aws("iam").create_service_linked_role(AWSServiceName="ecs.amazonaws.com")
        time.sleep(15)
        print("created AWSServiceRoleForECS")
    except aws("iam").exceptions.InvalidInputException:
        print("exists")
    say(f"ECS Fargate: cluster {CLUSTER}, service {N} (console + orchestrator in one task)")
    td = task_and_service(imgs, account, door, cog, subnets, task_sg, tg, exec_arn, task_arn)
    say("CloudFront (HTTPS) in front of the ALB")
    domain, dist_id = cloudfront(alb["DNSName"])
    url = f"https://{domain}"
    (CONF / "frontend.json").write_text(json.dumps({"url": url, "distribution_id": dist_id, "image_tag": tag,
                                                    "task_definition": td.rsplit("/", 1)[1]}, indent=1))
    print(f"\nconsole URL: {url}\nsign in with the passcode in ~/.claimsense/demo.json (never commit or print it)")


def status():
    f = CONF / "frontend.json"
    print(f.read_text() if f.exists() else "not deployed")
    s = aws("ecs").describe_services(cluster=CLUSTER, services=[N])["services"]
    if s:
        print(f"service: {s[0]['status']} · running {s[0]['runningCount']}/{s[0]['desiredCount']} · {s[0]['taskDefinition'].rsplit('/', 1)[1]}")


def destroy():
    ecs, elb, ec2, cf, iam = aws("ecs"), aws("elbv2"), aws("ec2"), aws("cloudfront"), aws("iam")
    for d in cf.list_distributions().get("DistributionList", {}).get("Items", []) or []:
        if d.get("Comment") == N:
            cfg = cf.get_distribution_config(Id=d["Id"])
            if cfg["DistributionConfig"]["Enabled"]:
                cfg["DistributionConfig"]["Enabled"] = False
                cf.update_distribution(Id=d["Id"], IfMatch=cfg["ETag"], DistributionConfig=cfg["DistributionConfig"])
                print("CloudFront: disabling (5-15 min)...", flush=True)
                cf.get_waiter("distribution_deployed").wait(Id=d["Id"], WaiterConfig={"Delay": 30, "MaxAttempts": 60})
            cf.delete_distribution(Id=d["Id"], IfMatch=cf.get_distribution_config(Id=d["Id"])["ETag"])
            print("CloudFront deleted")
    try:
        ecs.update_service(cluster=CLUSTER, service=N, desiredCount=0)
        ecs.delete_service(cluster=CLUSTER, service=N, force=True)
        ecs.get_waiter("services_inactive").wait(cluster=CLUSTER, services=[N])
        print("ECS service deleted")
    except Exception as e:
        print(f"ECS service: {type(e).__name__}")
    for arn in ecs.list_task_definitions(familyPrefix=N)["taskDefinitionArns"]:
        ecs.deregister_task_definition(taskDefinition=arn)
    try:
        alb = elb.describe_load_balancers(Names=[N])["LoadBalancers"][0]
        elb.delete_load_balancer(LoadBalancerArn=alb["LoadBalancerArn"])
        elb.get_waiter("load_balancers_deleted").wait(LoadBalancerArns=[alb["LoadBalancerArn"]])
        print("ALB deleted")
    except Exception as e:
        print(f"ALB: {type(e).__name__}")
    try:
        elb.delete_target_group(TargetGroupArn=elb.describe_target_groups(Names=[f"{N}-console"])["TargetGroups"][0]["TargetGroupArn"])
    except Exception:
        pass
    time.sleep(20)
    for name in (f"{N}-task", f"{N}-alb"):
        for g in ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": [name]}])["SecurityGroups"]:
            try:
                ec2.delete_security_group(GroupId=g["GroupId"])
            except Exception as e:
                print(f"security group {name}: {type(e).__name__} (retry destroy in a minute)")
    for r in (f"{N}-task", f"{N}-exec"):
        try:
            for p in iam.list_role_policies(RoleName=r)["PolicyNames"]:
                iam.delete_role_policy(RoleName=r, PolicyName=p)
            for p in iam.list_attached_role_policies(RoleName=r)["AttachedPolicies"]:
                iam.detach_role_policy(RoleName=r, PolicyArn=p["PolicyArn"])
            iam.delete_role(RoleName=r)
        except iam.exceptions.NoSuchEntityException:
            pass
    try:
        aws("secretsmanager").delete_secret(SecretId=DEMO_SECRET, ForceDeleteWithoutRecovery=True)
    except Exception:
        pass
    (CONF / "frontend.json").unlink(missing_ok=True)
    print("frontend removed (ECR images, the door, Cognito, DynamoDB and the dashboard are kept)")


if __name__ == "__main__":
    if (sys.argv[1:] or [""])[0] == "rotate-passcode":       # new passcode, then redeploy with `apply`
        (CONF / "demo.json").unlink(missing_ok=True)
        demo_secret()
        sys.exit(0)
    {"apply": apply, "status": status, "destroy": destroy}[(sys.argv[1:] or ["apply"])[0]]()
