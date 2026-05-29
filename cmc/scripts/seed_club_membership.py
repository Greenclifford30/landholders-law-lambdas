import argparse
from datetime import datetime, timezone

import boto3


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def put_seed_records(table_name, club_id, club_name, admin_user_id, admin_email):
    table = boto3.resource("dynamodb").Table(table_name)
    created_at = now_iso()
    table.put_item(
        Item={
            "PK": f"CLUB#{club_id}",
            "SK": "META",
            "clubId": club_id,
            "name": club_name,
            "createdAt": created_at,
            "updatedAt": created_at,
        }
    )
    table.put_item(
        Item={
            "PK": f"CLUB#{club_id}",
            "SK": f"MEMBER#{admin_user_id}",
            "GSI1PK": f"USER#{admin_user_id}",
            "GSI1SK": f"CLUB#{club_id}",
            "clubId": club_id,
            "userId": admin_user_id,
            "email": admin_email,
            "role": "admin",
            "createdAt": created_at,
            "updatedAt": created_at,
        }
    )


def main():
    parser = argparse.ArgumentParser(description="Seed initial Movie Club membership records.")
    parser.add_argument("--table-name", required=True)
    parser.add_argument("--club-id", required=True)
    parser.add_argument("--club-name", required=True)
    parser.add_argument("--admin-user-id", required=True, help="Cognito sub for the admin user.")
    parser.add_argument("--admin-email", required=True)
    args = parser.parse_args()
    put_seed_records(
        args.table_name,
        args.club_id,
        args.club_name,
        args.admin_user_id,
        args.admin_email,
    )


if __name__ == "__main__":
    main()
