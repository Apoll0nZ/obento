import json
import os
import boto3
from collections import defaultdict
from datetime import datetime
from boto3.dynamodb.conditions import Attr

# 環境変数から設定を取得
DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_TABLE_NAME']
TEAMS_COMMUNITY_EMAIL = os.environ['TEAMS_COMMUNITY_EMAIL']
SENDER_EMAIL = os.environ['SENDER_EMAIL']

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(DYNAMODB_TABLE_NAME)
ses_client = boto3.client('ses', region_name=os.environ['AWS_REGION'])

def lambda_handler(event, context):
    """メインのLambdaハンドラー（定期実行用）"""
    try:
        # 今日の日付を取得（例: 2025/08/15）
        today_date = datetime.now().strftime('%Y/%m/%d')
        
        # テーブル全体をスキャンし、本日の日付に一致するアイテムのみをフィルタリング
        response = table.scan(
            FilterExpression=Attr('date').eq(today_date)
        )
        items = response.get('Items', [])

        if not items:
            print("No cancellation data for today found. Exiting.")
            return {'statusCode': 200, 'body': 'No data for today'}
        
        # メール本文を作成
        email_body_parts = []
        email_body_parts.append(f'お世話になっております。\n\nお弁当について、本日（{today_date}）のキャンセルは以下の通りです。\n\n')

        cancellations_by_date = defaultdict(list)
        for item in items:
            cancellations_by_date[item.get('date')].append(item.get('name'))
        
        sorted_dates = sorted(cancellations_by_date.keys())
        for date_str in sorted_dates:
            names = cancellations_by_date[date_str]
            email_body_parts.append(f'【{date_str}のキャンセル】\n')
            email_body_parts.append(f'キャンセル人数：{len(names)}名\n')
            email_body_parts.append(f'欠勤者：{", ".join(names)}\n\n')
        
        email_body_parts.append('お手数をおかけしますが、ご対応のほどよろしくお願いいたします。\n\n')
        email_body_parts.append('--------------------\n部署名\n名前\n電話番号\n--------------------')
        
        full_email_body = "".join(email_body_parts)
        subject = f"お弁当キャンセルのお願い ({today_date})"

        # SESでメールを送信
        send_email_via_ses(SENDER_EMAIL, TEAMS_COMMUNITY_EMAIL, subject, full_email_body)

        # 本日のデータをDynamoDBテーブルからクリア
        clear_dynamodb_table(items)
        
        return {'statusCode': 200, 'body': 'Notification sent and data for today cleared successfully.'}
    
    except Exception as e:
        print(f"Error in teams_notifier: {e}")
        return {'statusCode': 500, 'body': f'Internal Server Error: {e}'}

def send_email_via_ses(source_email, destination_email, subject, body):
    """SESを使ってメールを送信する関数"""
    try:
        ses_client.send_email(
            Source=source_email,
            Destination={'ToAddresses': [destination_email]},
            Message={
                'Subject': {'Data': subject},
                'Body': {'Text': {'Data': body}}
            }
        )
        print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")
        raise

def clear_dynamodb_table(items):
    """DynamoDBテーブルから指定したアイテムを削除"""
    for item in items:
        # 複合プライマリーキー（nameとdate）の両方を指定して削除
        table.delete_item(Key={'name': item['name'], 'date': item['date']})