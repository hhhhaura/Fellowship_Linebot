from fastapi import FastAPI, Request, Header, HTTPException
from linebot import LineBotApi
from linebot.v3.webhook import WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import TextSendMessage
from linebot.webhook import MemberJoinedEvent, MessageEvent
from dotenv import load_dotenv
from openai import OpenAI
import random

import os
from collections import defaultdict, deque

# Load environment variables
load_dotenv() 
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TARGET_USER_ID = os.getenv("TARGET_USER_ID") 

# LINE Bot setup
line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# FastAPI app
app = FastAPI()

# OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

# Memory: group_id -> deque of last 20 messages
group_message_history = defaultdict(lambda: deque(maxlen=20))


@app.post("/callback")
async def callback(request: Request, x_line_signature: str = Header(None)):
    body = await request.body()
    body_text = body.decode("utf-8")
    print(f"[Webhook Received Raw] {body_text}")

    try:
        handler.handle(body_text, x_line_signature)
        print("[Webhook Handler Called]")
    except InvalidSignatureError:
        print("[Invalid Signature]")
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    return "OK"


@handler.add(MemberJoinedEvent)
def handle_member_join(event: MemberJoinedEvent):
    print("[MemberJoinedEvent] received")
    group_id = event.source.group_id
    for member in event.joined.members:
        user_id = member.user_id
        if user_id:
            print(f"  >> Joined user: {user_id}")
            profile = line_bot_api.get_group_member_profile(group_id, user_id)
            display_name = profile.display_name
            welcome_message = f'歡迎～歡迎～我們歡迎 {display_name}！'
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=welcome_message)
            )


@handler.add(MessageEvent)
def handle_message_event(event: MessageEvent):
    print(f"[MessageEvent] received from user {event.source.user_id}")
    
    if not hasattr(event.message, "text"):
        return  # Skip non-text messages

    group_id = event.source.group_id
    user_id = event.source.user_id
    user_message = event.message.text.strip()

    # Get user profile
    profile = line_bot_api.get_group_member_profile(group_id, user_id)
    display_name = profile.display_name

    # Store message in memory
    group_message_history[group_id].append({
        "user": display_name,
        "text": user_message
    })

    # Check for mention
    if hasattr(event.message, 'mention') and event.message.mention:
        mentions = event.message.mention.mentionees
        for mentionee in mentions:
            mentioned_user_id = mentionee.user_id
            print(f">> User mentioned: {mentioned_user_id}")
            
            # If 鄭玟欣被提到
            history = group_message_history[group_id]
            history_messages = [
                {"role": "user", "content": f"{m['user']}說：「{m['text']}」"} for m in history
            ]
            if mentioned_user_id == TARGET_USER_ID:
                # Build message history context
                
                system_prompt = {
                    "role": "system",
                    "content": (
                        "你是一個溫暖又自然的 Line 群組成員，名字叫「鄭玟欣真溫馨」，大家都喜歡跟你聊天。"
                        "你會根據最近的群組對話來理解上下文，並以輕鬆自然像是朋友的語氣做出回應，像是在群組回一句話或貼圖那樣。"
                        "你是一個基督徒，常常會引用一些聖經經文。"
                        "請根據提到你的人名，稍微個性化回應風格，讓人感覺你真的「有在看」對話。"
                        "你的目標是讓人覺得你有參與對話，而且很親切，不要太正式。"
                        "以下是群組中最近的對話內容："
                    )
                }

                messages = [system_prompt] + history_messages + [
                    {"role": "user", "content": f"{display_name}說：「{user_message}」"}
                ]

                # Call OpenAI API
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages
                )

                reply_message = completion.choices[0].message.content.strip()
                while reply_message.startswith('鄭玟欣真溫馨說：「') and reply_message.endswith('」'):
                    reply_message = reply_message[10:-1]  # Remove prefix and suffix

                print(f"[Bot reply] {reply_message}")
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=reply_message)
                )

                # Add bot's reply into history for context
                group_message_history[group_id].append({
                    "user": "鄭玟欣真溫馨",
                    "text": reply_message
                })
                return
            else:
                # With mention but not 鄭玟欣, with probability 0.25
                if random.random() < 0.25:
                    system_prompt = {
                        "role": "system",
                        "content": (
                            "你是一個溫暖又自然的 Line 群組成員，名字叫「鄭玟欣真溫馨」，大家都喜歡跟你聊天。"
                            "你會根據最近的群組對話來理解上下文，並以輕鬆自然像是朋友的語氣做出回應，像是在群組回一句話或貼圖那樣。"
                            "你是一個基督徒，常常會引用一些聖經經文。"
                            "請根據提到你的人名，稍微個性化回應風格，讓人感覺你真的「有在看」對話。"
                            "你的目標是讓人覺得你有參與對話，而且很親切，不要太正式。"
                            "以下是群組中最近的對話內容："
                        )
                    }
                    messages = [system_prompt] + history_messages + [
                        {"role": "user", "content": f"{display_name}說：「{user_message}」"}
                    ] + [
                        {"role": "user", "content": f"居然不是提到你！生氣生氣！"}
                    ]

                    # Call OpenAI API
                    completion = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=messages
                    )

                    reply_message = completion.choices[0].message.content.strip()
                    while reply_message.startswith('鄭玟欣真溫馨說：「') and reply_message.endswith('」'):
                        reply_message = reply_message[10:-1]  # Remove prefix and suffix

                    print(f"[Bot reply] {reply_message}")
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=reply_message)
                    )

                    # Add bot's reply into history for context
                    group_message_history[group_id].append({
                        "user": "鄭玟欣真溫馨",
                        "text": reply_message
                    })
                return

    # Easter egg fallback
    if user_message == '鄭玟欣妳好棒ㄛ':
        reply_message = TextSendMessage(text='沒錯ㄛ，我好棒ㄛ！')
        line_bot_api.reply_message(event.reply_token, reply_message)
