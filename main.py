from fastapi import FastAPI, Request, Header, HTTPException
from linebot import LineBotApi
from linebot.v3.webhook import WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import TextSendMessage
from linebot.webhook import MemberJoinedEvent, MessageEvent
from dotenv import load_dotenv
from openai import OpenAI

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

# Memory: group_id -> deque of last 10 messages
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
            if mentioned_user_id == TARGET_USER_ID:
                # Build message history context
                history = group_message_history[group_id]
                history_messages = [
                    {"role": "user", "content": f"{m['user']}說：「{m['text']}」"} for m in history
                ]

                system_prompt = {
                    "role": "system",
                    "content": "你是一個自然溫暖又親切的 Line Bot，名字叫「鄭玟欣真溫馨」。說話風格輕鬆、像朋友一樣，不做作也不太浮誇。每次有人提到你（mention 你），你都會回應，但回覆不要太長，要像朋友在群組回個貼圖那樣自然。我會告訴你是誰提到了你，你可以根據對方的名字稍微調整語氣。記得，你的重點是讓人感覺你在、你有回應，但不要講太多。"
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

                print(f"[Bot reply] {reply_message}")
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=reply_message)
                )
                return
            else:
                # Mentioned someone else
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text='叫他幹嘛！？叫我就好 🙋‍♀️')
                )
                return

    # Easter egg fallback
    if user_message == '鄭玟欣妳好棒ㄛ':
        reply_message = TextSendMessage(text='沒錯ㄛ，我好棒ㄛ！')
        line_bot_api.reply_message(event.reply_token, reply_message)
