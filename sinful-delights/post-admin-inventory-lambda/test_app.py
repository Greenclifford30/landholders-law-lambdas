import unittest
import json
from unittest.mock import patch, MagicMock
import sys
import os

# Add the parent directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from test_utils import mock_event, setup_mock_environment

# Import the Lambda function to test
from update_inventory_lambda.app import lambda_handler

class TestUpdateInventoryLambda(unittest.TestCase):
    def setUp(self):
        setup_mock_environment()

    @patch('update_inventory_lambda.app.dynamodb')
    def test_successful_inventory_update(self, mock_dynamodb):
        # Mock a successful DynamoDB update response
        mock_dynamodb.update_item.return_value = {
            'Attributes': {
                'StockQty': {'N': '15'}
            }
        }

        # Create a mock event with valid admin credentials and inventory update details
        event = mock_event({
            'itemId': 'test-item-1',
            'adjustment': 5
        }, is_admin=True)

        # Call the Lambda handler
        response = lambda_handler(event, None)

        # Assert successful response
        self.assertEqual(response['statusCode'], 200)
        
        # Verify DynamoDB update was called with correct parameters
        mock_dynamodb.update_item.assert_called_once()
        call_args = mock_dynamodb.update_item.call_args[1]
        self.assertEqual(call_args['Key'], {
            'PK': {'S': 'ITEM#test-item-1'},
            'SK': {'S': 'STOCK'}
        })

        # Parse response body and verify details
        body = json.loads(response['body'])
        self.assertEqual(body['itemId'], 'test-item-1')
        self.assertEqual(body['newStockQty'], 15)
        self.assertEqual(body['adjustment'], 5)

    def test_unauthorized_request(self):
        # Create a mock event without admin credentials
        event = mock_event({
            'itemId': 'test-item-1',
            'adjustment': 5
        }, is_admin=False)

        # Call the Lambda handler
        response = lambda_handler(event, None)

        # Assert unauthorized response
        self.assertEqual(response['statusCode'], 401)
        body = json.loads(response['body'])
        self.assertEqual(body['error'], 'Unauthorized')

    def test_missing_input_details(self):
        # Create a mock event with missing inventory details
        event = mock_event({}, is_admin=True)

        # Call the Lambda handler
        response = lambda_handler(event, None)

        # Assert bad request response
        self.assertEqual(response['statusCode'], 400)
        body = json.loads(response['body'])
        self.assertEqual(body['error'], 'Missing inventory adjustment details')

if __name__ == '__main__':
    unittest.main()