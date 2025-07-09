import boto3
import json
from decimal import Decimal

# Custom encoder to handle Decimal (used by DynamoDB for numbers)
class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            if o % 1 == 0:
                return int(o)
            else:
                return float(o)
        return super(DecimalEncoder, self).default(o)

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('Reunion_Attendees')

def lambda_handler(event, context):
    try:
        response = table.scan()
        items = response.get('Items', [])
        
        # Optionally transform data for dashboard display
        dashboard_data = {
            "total_attendees": len(items),
            "attendees": items
        }
        
        return {
            "statusCode": 200,
            "body": json.dumps(dashboard_data, cls=DecimalEncoder)
        }
        
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
