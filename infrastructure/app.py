from aws_cdk import core, aws_dynamodb as dynamo
from chalice.cdk import Chalice

from infrastructure.wrapper.wrapper_stack import WrapperAppStack

app = core.App()

env_ohio = core.Environment(region="us-east-2")

WrapperAppStack(app, 'WrapperApp', env=env_ohio)

app.synth()
