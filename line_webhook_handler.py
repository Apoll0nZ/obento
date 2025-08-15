import json
import os
import boto3
import re
from boto3.dynamodb.conditions import Key
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    SourceUser, SourceGroup
)
from datetime import datetime, timedelta

# 環境変数から設定を取得
LINE_CHANNEL_ACCESS_TOKEN = os.environ['LINE_CHANNEL_ACCESS_TOKEN']
LINE_CHANNEL_SECRET = os.environ['LINE_CHANNEL_SECRET']
DYNAMODB_TABLE_NAME = os.environ['DYNAMODB_TABLE_NAME']

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table(DYNAMODB_TABLE_NAME)

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # メッセージの先頭・末尾のスペースを削除し、全角スペースを半角に変換
    text = event.message.text.strip().replace('　', ' ')
    
    # ユーザー名を取得
    user_name = ""
    if isinstance(event.source, SourceUser):
        profile = line_bot_api.get_profile(event.source.user_id)
        user_name = profile.display_name
    elif isinstance(event.source, SourceGroup):
        try:
            profile = line_bot_api.get_group_member_profile(event.source.group_id, event.source.user_id)
            user_name = profile.display_name
        except:
            user_name = "グループメンバー"
    
    try:
        if text.startswith('@キャンセル'):
            # @キャンセル コマンドの処理
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f'デバッグ: @キャンセル コマンドを検出'))
            
            # `@キャンセル`の後のスペースをすべて取り除く
            name_to_delete = text.replace('@キャンセル', '', 1).strip()
            
            delete_from_dynamodb(name_to_delete, event.reply_token)
        
        elif text.startswith('@弁当'):
            # @弁当 コマンドの処理
            cancellation_date = datetime.now().strftime('%Y/%m/%d')

            # 日付を抽出（$YYYY/MM/DD または $MM/DD の形式）
            date_match_full = re.search(r'\$(\d{4}/\d{2}/\d{2})', text)
            date_match_short = re.search(r'\$(\d{1,2}/\d{1,2})', text)
            
            if date_match_full:
                cancellation_date = date_match_full.group(1)
            elif date_match_short:
                year = datetime.now().year
                cancellation_date_str = f"{year}/{date_match_short.group(1)}"
                cancellation_date = datetime.strptime(cancellation_date_str, '%Y/%m/%d').strftime('%Y/%m/%d')
            
            # 名前を抽出（#名前の形式）
            name_match = re.search(r'#(.+?)(?:\s|$)', text)
            if name_match:
                user_name = name_match.group(1).strip()
            
            if user_name:
                # DynamoDBにデータを書き込み
                table.put_item(
                    Item={
                        'name': user_name,
                        'date': cancellation_date
                    }
                )

                # ユーザーに返信
                reply_message = f"{user_name}さんの{cancellation_date}の欠席を記録しました。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_message))
            else:
                # 名前が空の場合
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f'デバッグ: 名前が空です。処理を中止'))
                reply_message = "ユーザー名を特定できませんでした。"
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_message))
            
    except Exception as e:
        print(f"処理中にエラーが発生しました: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"デバッグ: 処理中にエラーが発生しました: {e}"))
        error_message = "エラーが発生しました。もう一度お試しください。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=error_message))

def delete_from_dynamodb(name_to_delete, reply_token):
    try:
        # 名前でDynamoDBをクエリして、該当するすべてのアイテムを取得
        response = table.query(
            KeyConditionExpression=Key('name').eq(name_to_delete)
        )
        items = response.get('Items', [])

        if not items:
            reply_message = f"{name_to_delete}さんは欠席リストに見つかりませんでした。"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_message))
            return

        # 取得したすべてのアイテムをループして削除
        for item in items:
            table.delete_item(
                Key={
                    'name': item['name'],
                    'date': item['date']
                }
            )
        
        reply_message = f"{name_to_delete}さんの欠席連絡をすべてキャンセルしました。"
        line_bot_api.reply_message(reply_token, TextSendMessage(text=reply_message))

    except Exception as e:
        print(f"DynamoDBからの削除に失敗しました: {e}")
        error_message = "キャンセル処理に失敗しました。"
        line_bot_api.reply_message(reply_token, TextSendMessage(text=error_message))

def lambda_handler(event, context):
    try:
        signature = event['headers']['x-line-signature']
        body = event['body']
        handler.handle(body, signature)
    except InvalidSignatureError:
        return {'statusCode': 400, 'body': 'Invalid signature'}
    except Exception as e:
        return {'statusCode': 500, 'body': f'Error: {e}'}

    return {'statusCode': 200, 'body': 'OK'}