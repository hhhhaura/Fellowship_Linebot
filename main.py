from fastapi import FastAPI, Request, Header, HTTPException
from linebot import LineBotApi
from linebot.v3.webhook import WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import TextSendMessage
from linebot.webhook import MemberJoinedEvent, MessageEvent
from dotenv import load_dotenv
import os
load_dotenv() 
from openai import OpenAI

# credentials
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TARGET_USER_ID = os.getenv("TARGET_USER_ID") 

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

app = FastAPI()


client = OpenAI(
  api_key=OPENAI_API_KEY
)


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
            # Optionally filter for TARGET_USER_ID
            if user_id is not None:
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
    
    # Check if the message is a text message and contains mention
    if hasattr(event.message, 'mention') and event.message.mention:
        mentions = event.message.mention.mentionees
        for mentionee in mentions:
            mentioned_user_id = mentionee.user_id
            print(f">> User mentioned: {mentioned_user_id}")
            
            # You can take action based on a specific user being mentioned
            if mentioned_user_id == TARGET_USER_ID:
                profile = line_bot_api.get_group_member_profile(event.source.group_id, event.source.user_id)
                display_name = profile.display_name
                completion = client.chat.completions.create(
                    model="gpt-4o-mini",
                    store=True,
                    messages=[ 
                        { "role": "system", "content": "你是一個自然溫暖又親切的 Line Bot，名字叫「鄭玟欣真溫馨」。說話風格輕鬆、像朋友一樣，不做作也不太浮誇。每次有人提到你（mention 你），你都會回應，但回覆不要太長，大概一兩句就好，要像朋友在群組回個貼圖那樣自然。我會告訴你是誰提到了你，你可以根據對方的名字稍微調整語氣。記得，你的重點是讓人感覺你在、你有回應，但不要講太多。" },

                        {"role": "user", "content": f"{display_name}說：「{event.message.text.strip()}」"}
                    ]
                )
                reply_message = completion.choices[0].message.content

                print(reply_message)
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f'{reply_message}')
                )
                return
            else:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f'叫他幹嘛！？叫我就好')
                )
                return

    # Fallback or other logic
    if event.message.text.strip() == '鄭玟欣妳好棒ㄛ':
        reply_message = TextSendMessage(text='沒錯ㄛ，我好棒ㄛ！')
        line_bot_api.reply_message(event.reply_token, reply_message)