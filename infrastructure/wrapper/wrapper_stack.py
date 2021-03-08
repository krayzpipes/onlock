
import os

from aws_cdk import core, aws_dynamodb as dynamodb, aws_iam as iam
from chalice.cdk import Chalice as CdkChalice

RUNTIME_SOURCE_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, 'runtime', 'wrapper'
)


class WrapperAppStack(core.Stack):

    def __init__(self, scope: core.Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)
        self.wrapper_table = self._create_wrapper_table()

        self.chalice = CdkChalice(
            self,
            "WrapperChaliceApp",
            source_dir=RUNTIME_SOURCE_DIR,
            stage_config={
                'environment_variables': {
                    'WRAPPER_TABLE_NAME': self.wrapper_table.table_name,
                    'WRAPPER_APP_NAME': 'WrapperChaliceApp',
                    'WRAPPER_ENV': 'dev',
                }
            }
        )

        self._add_dynamo_permissions()

    def _create_wrapper_table(self) -> dynamodb.Table:
        table_settings = {
            'partition_key': dynamodb.Attribute(
                name='id',
                type=dynamodb.AttributeType.STRING,
            ),
        }
        return dynamodb.Table(self, "wrapperTable", **table_settings)

    def _add_dynamo_permissions(self):
        role = self.chalice.get_role('DefaultRole')
        self.wrapper_table.grant(role, "dynamodb:PutItem")
        self.wrapper_table.grant(role, "dynamodb:GetItem")
        self.wrapper_table.grant(role, "dynamodb:DeleteItem")

