"""Main app file for wrapper app."""

from datetime import datetime, timedelta
import json
import logging
import os
import re
import uuid

import boto3
from chalice import Chalice, Response
import pydantic

WRAPPER_APP_NAME = os.environ.get("WRAPPER_APP_NAME")
WRAPPER_ENV = os.environ.get("WRAPPER_ENV")
WRAPPER_TABLE_NAME= os.environ.get("WRAPPER_TABLE_NAME")

JSON_HEADERS = {'Content-Type': 'application/json'}

_DYNAMO = None


logger = logging.getLogger()
logger.setLevel(logging.INFO)


# TTL field validation
class WrapperTtl(pydantic.BaseModel):
    ttl: str

    @pydantic.validator('ttl')
    def validate_value(cls, v):
        if int(v) < 30:
            raise ValueError("must be greater than 30 seconds")
        return v


# ID field validation
class WrapperId(pydantic.BaseModel):
    id: str

    @pydantic.validator('id')
    def validate_id(cls, v):
        if re.search('[^a-zA-Z0-9]+', v):
            raise ValueError('id contains invalid characters')
        return v


# Validation for incoming Value field + TTL
class WrapperIn(WrapperTtl):
    value: str


# Validation for Outgoing ID + expire
class WrapperPostOut(WrapperId):
    expire: int


# Validation for outgoing response with value from GET request
class WrapperGetOut(WrapperPostOut):
    value: str


def get_dynamo_client():
    """Returns dynamo client. This setup helps during tests."""
    global _DYNAMO
    if _DYNAMO is None:
        _DYNAMO = boto3.client("dynamodb")
    return _DYNAMO


def random_id() -> str:
    """Generate unique id for tracking or sending back to user."""
    _uuid = str(uuid.uuid4()).replace("-", "")
    return f"{_uuid}"


def validation_jsonify(v: pydantic.ValidationError) -> dict:
    return json.loads(v.json())


app = Chalice(app_name=f"{WRAPPER_APP_NAME}-{WRAPPER_ENV}", debug=True)


@app.route("/v1/wrapper", methods=["POST"])
def v1_wrapper_post():
    """Save secret value to db and return id that references value."""

    request = app.current_request

    request_id = request.lambda_context.aws_request_id

    try:
        # Incoming json body validation
        try:
            logging.info('validating incoming json')
            WrapperIn(**request.json_body)
        except pydantic.ValidationError as e:
            logger.error(e.json())
            body = {
                'status': 'failed',
                'error': validation_jsonify(e),
                'ref': request_id,
            }
            logger.error(f"{body}")
            return Response(
                body={**body, 'ref': request_id},
                status_code=200,
                headers=JSON_HEADERS,
            )

        # This is the ID that will be saved as the 'key' in dynamodb
        # and will be passed back to the customer.
        wrap_id = random_id()

        dynamo = get_dynamo_client()
        _expire_datetime = datetime.utcnow() + timedelta(seconds=request.json_body['ttl'])
        expire = _expire_datetime.strftime('%s')

        # Create response and perform validations
        try:
            logging.info('trying to create and validate response')
            wrapper_out = WrapperPostOut(
                id=wrap_id,
                expire=expire,
            )
        except pydantic.ValidationError as e:
            logger.error(f"internal error, {e.__class__}, {e}")
            return Response(
                body={
                    'status': 'failed',
                    'error': "internal error",
                    'ref': request_id,
                },
                status_code=200,
                headers=JSON_HEADERS,
            )

        _ = dynamo.put_item(
            TableName=WRAPPER_TABLE_NAME,
            Item={
                'id': {'S': wrap_id},
                'value': {'S': request.json_body['value']},
                'ttl': {'N': expire},
            },
        )

        logger.info(f"{request_id} successful")
        return Response(
            body={
                'status': 'success',
                'data': json.loads(wrapper_out.json()),
                'ref': request_id,
            },
            status_code=200,
            headers=JSON_HEADERS,
        )
    except Exception as e:
        logger.error(f"internal error: {e.__class__}, {e}")
        return Response(
            body={
                'status': 'failed',
                'error': 'internal error',
                'ref': request_id,
            },
            status_code=200,
            headers=JSON_HEADERS,
        )


@app.route("/v1/wrapper/{wrap_id}", methods=["GET"])
def v1_wrapper_get(wrap_id):

    request = app.current_request
    request_id = request.lambda_context.aws_request_id

    try:
        try:
            WrapperId(id=wrap_id)
        except pydantic.ValidationError as e:
            logger.error(validation_jsonify(e))
            return Response(
                body={
                    'status': 'failed',
                    'error': validation_jsonify(e),
                    'ref': request_id,
                },
                status_code=200,
                headers=JSON_HEADERS,
            )

        dynamo = get_dynamo_client()
        response = dynamo.delete_item(
            TableName=WRAPPER_TABLE_NAME,
            Key={'id': {'S': wrap_id}},
            ReturnValues='ALL_OLD'
        )

        # Wrapper id likely not found
        if 'Attributes' not in response:
            logger.info(f"wrapper id not found or expired: {wrap_id}")
            return Response(
                body={
                    'status': 'failed',
                    'error': 'wrapper id not found or expired',
                    'ref': request_id,
                },
                status_code=200,
                headers=JSON_HEADERS,
            )

        # Perform validations for json going back to the client
        try:
            logging.info('creating and validating response for client')
            return_data = WrapperGetOut(
                id=response['Attributes']['id']['S'],
                value=response['Attributes']['value']['S'],
                expire=response['Attributes']['ttl']['N'],
            )
        except pydantic.ValidationError as e:
            logger.error(validation_jsonify(e))
            return Response(
                body={
                    'status': 'failed',
                    'error': validation_jsonify(e),
                    'ref': request_id,
                },
                status_code=200,
                headers=JSON_HEADERS,
            )

        logger.info(f"successful")
        return Response(
            body={
                'status': 'success',
                'data': json.loads(return_data.json()),
                'ref': request_id,
            },
            status_code=200,
            headers=JSON_HEADERS,
        )
    except Exception as e:
        logger.error(f"internal error: {e.__class__}, {e}")
        return Response(
            body={
                'status': 'failed',
                'error': 'internal error',
                'ref': request_id,
            }
        )
