"""The template model reads infra/template.yaml as data."""

import copy

import pytest

from tools.template_model import (
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
