"""The template model reads infra/template.yaml as data."""

from tools.template_model import TemplateModel, parse_template, possible_strings, template_model

TEMPLATE = parse_template(
    """
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


def test_the_checked_in_template_parses() -> None:
    model = template_model()

    assert "ApiFunction" in model.functions()
    assert model.consumers()["DiscoveryQueue"] == ["DiscoveryFunction"]
