import os
import json
import boto3

ses = boto3.client('ses')

def handler(event, context):
    """
    Receives JSON input from API Gateway with consultation data,
    then sends an email to the business owner via SES.
    """

    try:
        body = event.get("body")
        if body:
            body = json.loads(body)
        else:
            raise ValueError("No body in event")

        # Extract fields from the incoming request
        name = body.get("name", "N/A")
        phone = body.get("phone", "N/A")
        email = body.get("email", "N/A")
        requested_service = body.get("requestedService", "N/A")

        # Construct the email parameters
        owner_email = os.environ.get("OWNER_EMAIL", "owner@example.com")
        business_email = os.environ.get("BUSINESS_EMAIL")
        subject = "New Consultation Request"
        message_body = (
            f"Name: {name}\n"
            f"Phone: {phone}\n"
            f"Email: {email}\n"
            f"Requested Service: {requested_service}\n"
        )

        response = ses.send_email(
            Source=business_email,
            Destination={
                "ToAddresses": [owner_email],
            },
            Message={
                "Subject": {
                    "Data": subject
                },
                "Body": {
                    "Text": {
                        "Data": message_body
                    }
                }
            }
        )
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Consultation request received."
            })
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }
