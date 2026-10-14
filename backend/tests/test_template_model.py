"""The template model reads infra/template.yaml as data."""

import copy
import textwrap

import pytest

from tools.template_model import (
    Statement,
    TemplateModel,
    parse_template,
    possible_strings,
    substitute,
    template_model,
)

TEMPLATE = parse_template(
    """
Parameters:
  Switch:
    Type: String
    Default: "false"
    AllowedValues: ["true", "false"]
  Prefix:
    Type: String
    Default: /app
    AllowedPattern: ^/[a-z]+$
  Limit:
    Type: Number
    Default: 10
    MinValue: 1
    MaxValue: 25
  WorkerImageUri:
    Type: String
  Contact:
    Type: String
    Default: ""
Rules:
  ContactRequiredWhenOn:
    RuleCondition: !Equals [!Ref Switch, "true"]
    Assertions:
      - Assert: !Not [!Equals [!Ref Contact, ""]]
        AssertDescription: Contact is required when Switch is on.
Conditions:
  IsOn: !Equals [!Ref Switch, "true"]
Resources:
  WorkQueue:
    Type: AWS::SQS::Queue
    Properties:
      VisibilityTimeout: 60
      RedrivePolicy:
        deadLetterTargetArn: !GetAtt WorkDeadLetterQueue.Arn
        maxReceiveCount: 5
  WorkDeadLetterQueue:
    Type: AWS::SQS::Queue
  WorkDlqAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      Dimensions:
        - Name: QueueName
          Value: !GetAtt WorkDeadLetterQueue.QueueName
  Worker:
    Type: AWS::Serverless::Function
    Properties:
      PackageType: Image
      ImageUri: !Ref WorkerImageUri
      Timeout: 10
      Environment:
        Variables:
          SECRET_PARAMETER: !If [IsOn, !Sub "${Prefix}/secret", ""]
      Policies:
        - Statement:
            - Sid: ReadSecrets
              Action: [ssm:GetParameter]
              Resource: !Sub arn:${AWS::Partition}:ssm:region:account:parameter${Prefix}/*
        - !If
          - IsOn
          - Statement:
              - Sid: SendWork
                Action: sqs:SendMessage
                Resource: !GetAtt WorkQueue.Arn
          - !Ref AWS::NoValue
      Events:
        Work:
          Type: SQS
          Properties:
            Queue: !GetAtt WorkQueue.Arn
Outputs:
  WorkQueueUrl:
    Value: !Ref WorkQueue
"""
)


def test_intrinsic_functions_keep_their_cloudformation_form() -> None:
    queue = TEMPLATE["Resources"]["WorkQueue"]["Properties"]

    assert queue["RedrivePolicy"]["deadLetterTargetArn"] == {
        "Fn::GetAtt": ["WorkDeadLetterQueue", "Arn"]
    }
    assert TEMPLATE["Outputs"]["WorkQueueUrl"]["Value"] == {"Ref": "WorkQueue"}
    assert TEMPLATE["Conditions"]["IsOn"] == {
        "Fn::Equals": [{"Ref": "Switch"}, "true"]
    }


def test_queues_know_their_dead_letter_queue_alarm_and_output() -> None:
    model = TemplateModel(TEMPLATE)
    queue = model.queue("WorkQueue")

    assert (queue.visibility_timeout, queue.dead_letter_queue, queue.max_receive_count) == (
        60,
        "WorkDeadLetterQueue",
        5,
    )
    assert model.queue("WorkDeadLetterQueue").retention == 345600
    assert model.dead_letter_queues() == {"WorkDeadLetterQueue"}
    assert model.alarms_watching("WorkDeadLetterQueue") == ["WorkDlqAlarm"]
    assert model.outputs_referencing("WorkQueue") == ["WorkQueueUrl"]


def test_functions_report_queues_and_grants_including_conditional_ones() -> None:
    worker = TemplateModel(TEMPLATE).function("Worker")

    assert worker.timeout == 10
    assert worker.consumed_queues == ["WorkQueue"]
    assert worker.send_message_targets == {"WorkQueue"}
    assert [statement.condition for statement in worker.statements] == [None, "IsOn"]
    assert worker.readable_parameter_patterns == ["${Prefix}/*"]
    assert worker.can_read_parameter("${Prefix}/secret")
    assert not worker.can_read_parameter("${Other}/secret")


def test_possible_strings_look_through_conditions() -> None:
    value = TEMPLATE["Resources"]["Worker"]["Properties"]["Environment"]["Variables"][
        "SECRET_PARAMETER"
    ]

    assert possible_strings(value) == ["${Prefix}/secret", ""]


def test_substitute_fills_references_and_refuses_unknown_ones() -> None:
    assert substitute("${Prefix}/secret", {"Prefix": "/app"}) == "/app/secret"
    with pytest.raises(KeyError, match="Other"):
        substitute("${Other}/secret", {"Prefix": "/app"})


def test_parameters_say_why_a_value_is_refused() -> None:
    parameters = TemplateModel(TEMPLATE).parameter_definitions()

    assert list(parameters) == ["Switch", "Prefix", "Limit", "WorkerImageUri", "Contact"]
    assert [parameters[name].default for name in ("Switch", "Limit", "WorkerImageUri")] == [
        "false",
        "10",
        None,
    ]
    assert parameters["Switch"].problems("true") == []
    assert parameters["Switch"].problems("yes") == ["Switch must be one of true, false, not 'yes'"]
    assert parameters["Prefix"].problems("/App") == ["Prefix '/App' does not match ^/[a-z]+$"]
    assert parameters["Limit"].problems("25") == []
    assert parameters["Limit"].problems("26") == ["Limit must be at most 25, not 26"]
    assert parameters["Limit"].problems("0") == ["Limit must be at least 1, not 0"]
    assert parameters["Limit"].problems("ten") == ["Limit must be a number, not 'ten'"]


VALUES = {"Switch": "true", "Prefix": "/app", "Limit": "10", "WorkerImageUri": "uri", "Contact": ""}


def test_rules_report_the_assertions_a_set_of_values_fails() -> None:
    model = TemplateModel(TEMPLATE)

    assert model.rule_failures(VALUES) == ["Contact is required when Switch is on."]
    assert model.rule_failures({**VALUES, "Contact": "ops@example.com"}) == []
    assert model.rule_failures({**VALUES, "Switch": "false"}) == []


def test_rules_evaluate_and_or_and_named_conditions() -> None:
    document = copy.deepcopy(TEMPLATE)
    document["Rules"] = {
        "Combined": {
            "RuleCondition": {
                "Fn::Or": [{"Condition": "IsOn"}, {"Fn::Equals": [{"Ref": "Limit"}, 25]}]
            },
            "Assertions": [
                {
                    "Assert": {
                        "Fn::And": [
                            {"Fn::Not": [{"Fn::Equals": [{"Ref": "Contact"}, ""]}]},
                            {"Fn::Equals": [{"Ref": "Prefix"}, "/app"]},
                        ]
                    },
                    "AssertDescription": "Needs a contact under /app.",
                }
            ],
        }
    }
    model = TemplateModel(document)
    off = {**VALUES, "Switch": "false"}

    assert model.rule_failures(off) == []
    assert model.rule_failures({**off, "Limit": "25"}) == ["Needs a contact under /app."]
    assert model.rule_failures(VALUES) == ["Needs a contact under /app."]
    assert model.rule_failures({**VALUES, "Contact": "ops@example.com"}) == []


def test_rules_refuse_an_intrinsic_they_cannot_evaluate() -> None:
    document = copy.deepcopy(TEMPLATE)
    [assertion] = document["Rules"]["ContactRequiredWhenOn"]["Assertions"]
    assertion["Assert"] = {"Fn::Contains": [["ops@example.com"], {"Ref": "Contact"}]}

    # The rule does not apply while the switch is off, and it still refuses.
    with pytest.raises(ValueError, match="Fn::Contains"):
        TemplateModel(document).rule_failures({**VALUES, "Switch": "false"})


def test_image_functions_know_their_image_parameter() -> None:
    model = TemplateModel(TEMPLATE)

    assert model.function("Worker").image_parameter == "WorkerImageUri"
    assert model.image_parameters() == {"WorkerImageUri": ["Worker"]}


def test_secrets_behind_a_switch_name_the_switch() -> None:
    assert TemplateModel(TEMPLATE).gated_secrets() == {"${Prefix}/secret": "Switch"}


def test_a_secret_behind_a_compound_condition_is_refused() -> None:
    document = copy.deepcopy(TEMPLATE)
    document["Conditions"]["IsOn"] = {
        "Fn::And": [
            {"Fn::Equals": [{"Ref": "Switch"}, "true"]},
            {"Fn::Equals": [{"Ref": "Limit"}, 10]},
        ]
    }

    with pytest.raises(ValueError, match="SECRET_PARAMETER"):
        TemplateModel(document).gated_secrets()


ROLES = parse_template(
    """
Parameters:
  ZoneId:
    Type: String
    Default: "*"
Conditions:
  HasZone: !Not [!Equals [!Ref ZoneId, "*"]]
Resources:
  DeployRole:
    Type: AWS::IAM::Role
    Properties:
      Policies:
        - PolicyName: Deploy
          PolicyDocument:
            Statement:
              - Sid: ChangeAppStack
                Effect: Allow
                Action: [cloudformation:CreateChangeSet, cloudformation:Describe*]
                Resource: !Sub >-
                  arn:${AWS::Partition}:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/app/*
                Condition:
                  ArnEquals:
                    cloudformation:RoleArn: !GetAtt ExecutionRole.Arn
              - Sid: PassExecutionRole
                Effect: Allow
                Action: iam:PassRole
                Resource: !GetAtt ExecutionRole.Arn
              - Sid: ChangeRecords
                Effect: Allow
                Action: route53:ChangeResourceRecordSets
                Resource: !If [HasZone, !Sub "arn:aws:route53:::hostedzone/${ZoneId}", "*"]
        - !If
          - HasZone
          - PolicyName: ReadZone
            PolicyDocument:
              Statement:
                - Sid: ReadZone
                  Effect: Allow
                  Action: route53:GetHostedZone
                  Resource: !Sub arn:aws:route53:::hostedzone/${ZoneId}
          - !Ref AWS::NoValue
        - PolicyName: InspectTemplates
          PolicyDocument:
            Statement:
              Sid: InspectTemplates
              Effect: Allow
              Action: cloudformation:GetTemplateSummary
              Resource: "*"
  ExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: app-execution
"""
)
ROLE_VALUES = {
    "AWS::Partition": "aws",
    "AWS::Region": "ap-southeast-2",
    "AWS::AccountId": "123456789012",
    "ZoneId": "*",
    "ExecutionRole.Arn": "arn:aws:iam::123456789012:role/app-execution",
}
STACK_ARN = "arn:aws:cloudformation:ap-southeast-2:123456789012:stack/app/1a2b3c"
ZONE_ARN = "arn:aws:route53:::hostedzone/Z1"


def _role_statement(sid: str, document: dict = ROLES) -> Statement:
    [statement] = [
        statement
        for statement in TemplateModel(document).role_statements("DeployRole")
        if statement.sid == sid
    ]
    return statement


def test_role_statements_read_iam_role_policies_and_conditions() -> None:
    statements = TemplateModel(ROLES).role_statements("DeployRole")

    # InspectTemplates' Statement block is one statement rather than a list.
    assert [statement.sid for statement in statements] == [
        "ChangeAppStack",
        "PassExecutionRole",
        "ChangeRecords",
        "ReadZone",
        "InspectTemplates",
    ]
    assert [statement.condition for statement in statements] == [
        None,
        None,
        None,
        "HasZone",
        None,
    ]
    assert statements[0].iam_condition == {
        "ArnEquals": {"cloudformation:RoleArn": {"Fn::GetAtt": ["ExecutionRole", "Arn"]}}
    }
    assert statements[1].iam_condition == {}
    assert TemplateModel(ROLES).role_statements("ExecutionRole") == []


def test_statements_cover_an_arn_once_their_references_are_filled_in() -> None:
    change = _role_statement("ChangeAppStack")
    pass_role = _role_statement("PassExecutionRole")
    no_region = {name: value for name, value in ROLE_VALUES.items() if name != "AWS::Region"}

    assert change.covers("cloudformation:CreateChangeSet", STACK_ARN, ROLE_VALUES)
    assert change.covers("cloudformation:DescribeStacks", STACK_ARN, ROLE_VALUES)
    assert not change.covers("cloudformation:DeleteStack", STACK_ARN, ROLE_VALUES)
    assert not change.covers(
        "cloudformation:CreateChangeSet", STACK_ARN.replace("/app/", "/app-copy/"), ROLE_VALUES
    )
    assert pass_role.covers("iam:PassRole", ROLE_VALUES["ExecutionRole.Arn"], ROLE_VALUES)
    assert not pass_role.covers(
        "iam:PassRole", "arn:aws:iam::123456789012:role/app-other", ROLE_VALUES
    )
    with pytest.raises(KeyError, match="AWS::Region"):
        change.covers("cloudformation:CreateChangeSet", STACK_ARN, no_region)


def test_a_grant_that_depends_on_a_template_condition_is_refused() -> None:
    records = _role_statement("ChangeRecords")
    read_zone = _role_statement("ReadZone")
    zoned = {**ROLE_VALUES, "ZoneId": "Z1"}

    # Both branches cover the zone, whichever one HasZone picks.
    assert records.covers("route53:ChangeResourceRecordSets", ZONE_ARN, zoned)
    assert records.covers("route53:ChangeResourceRecordSets", ZONE_ARN, ROLE_VALUES)
    # Only the "*" branch covers another zone.
    with pytest.raises(ValueError, match="ChangeRecords"):
        records.covers("route53:ChangeResourceRecordSets", ZONE_ARN.replace("Z1", "Z2"), zoned)
    # ReadZone is granted only under HasZone.
    with pytest.raises(ValueError, match="ReadZone"):
        read_zone.covers("route53:GetHostedZone", ZONE_ARN, zoned)
    assert not read_zone.covers("route53:GetHostedZone", ZONE_ARN.replace("Z1", "Z2"), zoned)


def _role(properties: str) -> TemplateModel:
    """A template whose one resource is DeployRole, an IAM role with these YAML properties."""
    return TemplateModel(
        parse_template(
            "Resources:\n  DeployRole:\n    Type: AWS::IAM::Role\n    Properties:\n"
            + textwrap.indent(textwrap.dedent(properties), "      ")
        )
    )


def _deploy_policy(statements: str) -> str:
    """Role properties with one policy whose Statement block is this YAML."""
    return (
        "Policies:\n  - PolicyName: Deploy\n    PolicyDocument:\n      Statement:\n"
        + textwrap.indent(textwrap.dedent(statements), "        ")
    )


# Each of these would grant more, or less, than a reader of its statements sees.
REFUSED_ROLES = {
    "managed policy": (
        "ManagedPolicyArns: [arn:aws:iam::aws:policy/AdministratorAccess]",
        "managed policies",
    ),
    "permissions boundary": (
        "PermissionsBoundary: arn:aws:iam::123456789012:policy/boundary",
        "permissions boundary",
    ),
    "policy without a PolicyDocument": (
        "Policies: [arn:aws:iam::aws:policy/AdministratorAccess]",
        "PolicyDocument is not one the model can read",
    ),
    "Policies under !If": (
        "Policies: !If [HasZone, [], !Ref AWS::NoValue]",
        "Policies is Fn::If",
    ),
    "PolicyDocument under !If": (
        """
        Policies:
          - PolicyName: Deploy
            PolicyDocument: !If
              - HasZone
              - Statement: [{Effect: Allow, Action: sqs:SendMessage, Resource: "*"}]
              - Statement: [{Effect: Allow, Action: sqs:ListQueues, Resource: "*"}]
        """,
        "PolicyDocument is not one the model can read",
    ),
    "Statement block under !If": (
        """
        Policies:
          - PolicyName: Deploy
            PolicyDocument:
              Statement: !If
                - HasZone
                - [{Effect: Allow, Action: ecr:BatchDeleteImage, Resource: "*"}]
                - []
        """,
        "Statement is Fn::If",
    ),
    "statement under !If": (
        _deploy_policy(
            """
            - !If
              - HasZone
              - {Effect: Allow, Action: ecr:BatchDeleteImage, Resource: "*"}
              - !Ref AWS::NoValue
            """
        ),
        "statement is not one the model can read",
    ),
    "Deny": (
        _deploy_policy("- {Sid: NoPush, Effect: Deny, Action: ecr:PutImage, Resource: '*'}"),
        "NoPush is a Deny",
    ),
    "Effect under !If": (
        _deploy_policy(
            """
            - Sid: MaybeDelete
              Effect: !If [HasZone, Allow, Deny]
              Action: ecr:BatchDeleteImage
              Resource: "*"
            """
        ),
        "MaybeDelete has Effect",
    ),
    "Action under !If": (
        _deploy_policy(
            """
            - Sid: MaybeDelete
              Effect: Allow
              Action: !If [HasZone, ecr:BatchDeleteImage, ecr:DescribeImages]
              Resource: "*"
            """
        ),
        "MaybeDelete has an Action",
    ),
    "NotAction": (
        _deploy_policy("- {Sid: AllButIam, Effect: Allow, NotAction: 'iam:*', Resource: '*'}"),
        "AllButIam uses NotAction",
    ),
    "NotResource": (
        _deploy_policy(
            """
            - Sid: PassOtherRoles
              Effect: Allow
              Action: iam:PassRole
              NotResource: arn:aws:iam::123456789012:role/app-execution
            """
        ),
        "PassOtherRoles uses NotResource",
    ),
}


@pytest.mark.parametrize(("properties", "refusal"), REFUSED_ROLES.values(), ids=REFUSED_ROLES)
def test_role_grants_the_model_cannot_read_are_refused(properties: str, refusal: str) -> None:
    with pytest.raises(ValueError, match=refusal):
        _role(properties).role_statements("DeployRole")


def test_a_function_grant_the_model_cannot_read_is_refused() -> None:
    document = copy.deepcopy(TEMPLATE)
    [read_secrets] = document["Resources"]["Worker"]["Properties"]["Policies"][0]["Statement"]
    read_secrets["Effect"] = "Deny"

    with pytest.raises(ValueError, match="ReadSecrets is a Deny"):
        TemplateModel(document).function("Worker").statements


def test_a_resource_the_model_cannot_fill_in_is_refused() -> None:
    joined = copy.deepcopy(ROLES)
    deploy = joined["Resources"]["DeployRole"]["Properties"]["Policies"][0]
    deploy["PolicyDocument"]["Statement"][1]["Resource"] = {
        "Fn::Join": [":", ["arn:aws:iam:", {"Ref": "AWS::AccountId"}, "role/app-execution"]]
    }

    with pytest.raises(ValueError, match="Fn::Join"):
        _role_statement("PassExecutionRole", joined).covers(
            "iam:PassRole", ROLE_VALUES["ExecutionRole.Arn"], ROLE_VALUES
        )


def test_actions_match_whatever_their_case_as_in_iam() -> None:
    """IAM ignores case in an action, so ``ECR:batchdeleteimage`` still deletes images."""
    [statement] = _role(
        _deploy_policy(
            "- {Effect: Allow, Action: [ECR:batchdeleteimage, cloudformation:Describe*], "
            "Resource: '*'}"
        )
    ).role_statements("DeployRole")

    assert statement.allows("ecr:BatchDeleteImage")
    assert statement.allows("CloudFormation:describestacks")
    assert not statement.allows("ecr:PutImage")
    assert statement.covers(
        "ecr:BatchDeleteImage", "arn:aws:ecr:ap-southeast-2:123456789012:repository/app", {}
    )


def test_the_checked_in_template_parses() -> None:
    model = template_model()

    assert "ApiFunction" in model.functions()
    assert model.consumers()["DiscoveryQueue"] == ["DiscoveryFunction"]


def test_the_checked_in_template_gates_the_brevo_and_marketaux_secrets() -> None:
    assert template_model().gated_secrets() == {
        "${ParameterPathPrefix}/brevo-api-key": "NotificationsEnabled",
        "${ParameterPathPrefix}/marketaux-api-token": "MarketauxEnabled",
    }


def test_the_checked_in_template_deploys_every_image_function_from_three_parameters() -> None:
    model = template_model()
    image_parameters = model.image_parameters()

    assert set(image_parameters) == {"ApiImageUri", "ScraperImageUri", "AnalysisImageUri"}
    assert sorted(sum(image_parameters.values(), [])) == model.image_functions()


def test_the_checked_in_template_needs_a_sender_when_notifications_are_on() -> None:
    model = template_model()
    defaults = {
        name: parameter.default or "" for name, parameter in model.parameter_definitions().items()
    }

    assert model.rule_failures(defaults) == []
    assert model.rule_failures({**defaults, "NotificationsEnabled": "true"}) == [
        "AlertSenderEmail is required when notifications are enabled."
    ]


def test_every_checked_in_default_passes_its_own_constraints() -> None:
    for parameter in template_model().parameter_definitions().values():
        if parameter.default is not None:
            assert parameter.problems(parameter.default) == [], parameter.name
